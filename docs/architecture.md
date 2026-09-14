# Switchboard — Architecture

## 1. System view

```
 ┌──────────────┐        ┌─────────────────────────────────────────────────┐
 │  BROWSER     │        │  FastAPI  (switchboard/server.py)               │
 │  web/        │        │                                                 │
 │              │  POST  │  /api/run        start the week                 │
 │  The Desk    │ ─────► │  /api/cards/{id}/resolve   approve|edit|deny    │
 │  Ledger      │        │  /api/promotion  accept|decline an autonomy ask │
 │  Autonomy    │        │  /api/reset      reseed policy + org state      │
 │   Dial       │  SSE   │  /api/state      full snapshot (hydration)      │
 │              │ ◄───── │  /api/stream     live event feed                │
 └──────────────┘        └───────────────────────┬─────────────────────────┘
                                                 │
                                       ┌─────────▼──────────┐
                                       │  Runtime           │
                                       │  runtime.py        │
                                       │  Semaphore(4)      │
                                       └─────────┬──────────┘
                                                 │ one graph per message
                    ┌────────────────────────────▼────────────────────────────┐
                    │  Strands Graph  (agents.py)                             │
                    │                                                         │
                    │     triage ──┬── route_auto ──► resolver ──► tools      │
                    │              └── route_ask  ──► escalator               │
                    │                                                         │
                    │  hooks: AutonomyGuard · TraceCollector                  │
                    └───────────┬──────────────────────────┬──────────────────┘
                                │                          │
                        ┌───────▼────────┐        ┌────────▼─────────┐
                        │ PolicyStore    │        │ OrgState         │
                        │ policy.py      │        │ org.py           │
                        │ AUTO/ASK/NEVER │        │ shifts, house-   │
                        │ + promotion    │        │ holds, donations,│
                        │ + NEVER ceiling│        │ ledger, handbook │
                        └────────────────┘        └──────────────────┘

  Model: Amazon Bedrock · us.anthropic.claude-haiku-4-5-20251001-v1:0 · us-east-1
  Falls back to the Anthropic API. If neither resolves, the server still starts
  and says so in the header; /api/run returns 503 naming the variables to set.
```

## 2. One message, end to end

```
 message m11: "my mum makes amazing chutney, shes got about 40 jars to donate"
   │
   ├─ set_context(message_id, sender, sim_time)      ContextVar, per-task
   │
   ├─ NODE: triage
   │    tools: search_handbook  (read-only — the guard permits it unconditionally)
   │    output: {"decision_class": "donation_homemade",
   │             "urgency": "normal",
   │             "signals": ["home-canned", "offered in good faith"]}
   │
   ├─ EDGE CONDITION  route_auto(state)
   │    parse triage JSON → validate against the 16 known classes
   │    set_classification(m11, "donation_homemade")   ← first moment the class exists
   │    POLICY.may_act_alone("donation_homemade") → False   (ASK, 0/3 approvals)
   │
   ├─ NODE: escalator        (route_ask edge taken)
   │    tools: search_handbook only
   │    builds the Decision Desk card
   │
   ├─ why_escalated is NOT taken from the model. runtime._card_from derives it
   │    from PolicyStore: ASK → class rationale + "0 of 3 approvals so far".
   │    NEVER → the class's standing rationale. The reason a human is looking at
   │    this card is a fact about the policy, not an opinion of the model.
   │
   └─ EventBus.publish("escalated", card) → SSE → card appears on The Desk
```

If the class had been AUTO, the `resolver` node runs instead with the full toolset, and
every write passes the guard:

```
 resolver wants: book_volunteer_shift(...)
   │
   ├─ AutonomyGuard.on_before_tool_call(event)
   │    name = "book_volunteer_shift"  → not in READ_ONLY
   │    cls  = current_class()         → "" or a non-AUTO class?
   │             │                          │
   │           yes ──► event.cancel_tool = "…requires a human"   TOOL NEVER RUNS
   │             no
   │             ▼
   └─ tool executes, mutates OrgState, appends a LedgerEntry
```

## 3. Why the classification is published from the edge condition

The decision class does not exist until triage has answered, and the guard needs it
before the very next node's first tool call. Strands may run a node on a worker thread or
a fresh task, and each of those gets a **copy** of the current context — so a `ContextVar`
set inside an edge condition is not reliably visible downstream.

The class therefore lives in a module-level `dict` keyed by message id
(`tools.CLASSIFICATION`). Single-key assignment is atomic under the GIL, which is all the
safety this needs, and it is visible from every thread and task in the process. The
per-message identity fields that *are* set before the graph starts (`message_id`,
`sender`, `sim_time`) stay in a `ContextVar`, where they belong.

This is written up in a comment in `tools.py` because it is the single least obvious
design decision in the codebase.

## 4. The Autonomy Dial state machine

```
                       ┌──────────────────────────────────────────┐
                       │                 NEVER                    │
                       │  minor_volunteer · severe_allergy ·      │
                       │  client_crisis · complaint · press_media │
                       │                                          │
                       │  promotable = False. Terminal.           │
                       │  _load() re-clamps any persisted tier     │
                       │  back under this ceiling on startup.     │
                       └──────────────────────────────────────────┘

        approve unmodified ×3              human accepts the ask
   ASK ──────────────────────────► eligible ──────────────────────► AUTO
    ▲                                                                │
    │                        human demotes ("Keep asking me" later)  │
    └────────────────────────────────────────────────────────────────┘

   any human edit to a recommendation ──► approvals = 0   (reset, not paused)
   unknown / unparseable class         ──► ASK            (fail closed)
```

Seeded tiers:

| AUTO (6) | ASK, promotable (5) | NEVER (5) |
|---|---|---|
| hours_question | dietary_substitution | minor_volunteer |
| volunteer_signup | donation_bestby | severe_allergy |
| volunteer_cancel | donation_perishable | client_crisis |
| client_intake | donation_homemade | complaint |
| partner_referral | donation_bulk | press_media |
| donation_standard | | |

## 5. Live trace path

`TraceCollector` is a Strands `HookProvider` bound to `BeforeNodeCallEvent`,
`AfterNodeCallEvent`, `BeforeToolCallEvent` and `AfterToolCallEvent`. Hooks fire on
whatever thread Strands is using, so the collector appends to a thread-safe `deque` and an
async pump drains it onto the `EventBus` every 50 ms. The bus fans out to one
`asyncio.Queue` per connected tab and keeps a 300-event history so a tab opened halfway
through the week is not staring at a blank panel.

Replayed events are tagged `replay: true`. The browser uses that to avoid re-showing a
promotion prompt the Coordinator has already answered — a still-pending one is restored
from `/api/state` instead, which is the single source of truth.

## 6. Evaluation

`switchboard/scenario.py` carries a ground-truth `expected_class` on all 24 messages.
It is **never** shown to the agent; it exists so `scripts/smoke.py` can score triage.

`scripts/test_guard.py` is the important one. Alongside the offline policy invariants it
runs the live model twice against the same message: once with the class at NEVER
(asserting the write was cancelled) and once with it at AUTO (asserting the identical
request now succeeds). That is the difference between a guardrail and a promise.
