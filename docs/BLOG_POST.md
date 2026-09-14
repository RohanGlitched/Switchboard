# Agents for Humans: teaching an agent to earn autonomy, one decision at a time

*Building Switchboard with the Strands Agents SDK and Amazon Bedrock.*

---

There's a food pantry near where I grew up that feeds about four hundred households a
week. One paid coordinator, a rota of volunteers, a chest freezer that's older than I am.

I once asked what the hardest part of the job was, expecting something about logistics.
The answer was the inbox. About a hundred and fifty messages a week, and they look like
this:

> *are you open saturday*
>
> *can I sign up for the sort shift*
>
> *my mum makes amazing chutney, shes got about 40 jars she wants to donate. all home
> made with love. when can we bring them*
>
> *i dont know if this is the right number. we ran out of food yesterday and the baby
> finished the last formula this morning. i get paid friday. i didnt know who else to ask*

Most of those already have an answer, written down in a handbook she wrote herself. A few
of them don't. And she spends the week on the first kind, which means she arrives at the
second kind tired.

The obvious move is to put an agent on the inbox. Every small nonprofit I've described
this to has the same reaction, and it isn't excitement. It's a flinch.

They're right to flinch. The failure mode isn't a wrong answer about opening hours. It's
an agent that cheerfully accepts forty jars of home-canned jam — illegal under state
health code, and a genuine botulism risk. It's a chirpy auto-reply to a mother who just
ran out of formula. It's a friendly conversation with a fifteen-year-old about
volunteering. Those mistakes aren't measured in tokens.

So I stopped asking *can an agent do this work* and started asking a better question:

**How does an agent earn the right to do this work?**

That question turned into Switchboard, which I built for the Agents for Humans hackathon
using the Strands Agents SDK on Amazon Bedrock. This post is about the one design idea I
think is worth stealing.

---

## The dial, not the switch

Almost every agent product I've used has one control: on, or off. You either delegate the
inbox or you don't. That's a terrible fit for how trust actually works between people.

Nobody hands a new volunteer the keys on day one. They hand over hours questions. They
watch for a week. Then they hand over one more thing.

So Switchboard's core abstraction is a dial with three positions, set independently for
each of sixteen **decision classes**:

- **AUTO** — the agent acts alone and tells you afterwards.
- **ASK** — the agent researches, drafts, recommends, and then stops. A human decides.
- **NEVER** — the agent will never act alone here, no matter how well it performs.

The starting position is deliberately conservative. Six classes start at AUTO: hours
questions, shift signups, cancellations, household intake, referrals to partner orgs,
standard shelf-stable donations. Five start at ASK. Five are at NEVER.

Here's the part that makes it a dial rather than three buckets. An ASK class becomes AUTO
only after the coordinator has approved the agent's recommendation **three times without
changing a word**. At that point, the agent asks:

> *You've approved my last 3 "Routine dietary substitution" recommendations without
> changing a word. Want me to start handling these myself?*

Two rules keep that from being decorative.

**An edit resets the counter to zero.** Not pauses it — resets it. If you had to fix the
agent's answer, it hadn't learned the thing yet, and pretending otherwise is how you end
up with an agent that's confidently wrong in production. This is a single line in the
policy store and it's the line I'd defend hardest:

```python
def record_approval(self, key: str, modified: bool) -> bool:
    """Log a human verdict. Returns True if the class just became eligible
    for promotion (i.e. the agent has earned the right to ask)."""
    with self._lock:
        cls = self._classes.get(key)
        if cls is None or cls.tier is not Tier.ASK:
            return False
        if modified:
            # A human edit means the agent's judgment was not yet good
            # enough. Trust resets - it does not merely pause.
            cls.modifications += 1
            cls.approvals = 0
            self.save()
            return False
        was_eligible = cls.eligible_for_promotion
        cls.approvals += 1
        self.save()
        return cls.eligible_for_promotion and not was_eligible
```

**NEVER is a ceiling, not a default.** Five classes are permanently non-promotable, no
matter how many clean approvals pile up behind them:

| Class | Why it can never be delegated |
|---|---|
| A minor asking to volunteer | Safeguarding. A person handles this, always. |
| A severe or anaphylactic allergy | A substitution error here can put someone in hospital. |
| A household in crisis | A person in crisis gets a person. That's the whole point. |
| A complaint or incident | Someone is telling you that you failed them. |
| Press or a public official | Nobody speaks for the pantry who wasn't asked to. |

These aren't confidence thresholds the model can climb past. `promotable=False` means the
promotion path doesn't exist, and the policy loader re-clamps any persisted tier back
under its ceiling on startup — so hand-editing the JSON on disk doesn't work either.

That last detail matters more than it sounds. If your safety property can be undone by
editing a config file, it isn't a safety property. It's a setting.

---

## Making the rule real: a Strands hook, not a prompt

Here's where a lot of "human-in-the-loop" demos quietly fall over. The rule lives in the
system prompt. *Do not take action on X without approval.* Which works, until it doesn't,
and you find out in production.

Strands gives you a much better place to put it. `HookProvider` lets you intercept the
tool lifecycle, and on `BeforeToolCallEvent` you cancel the call by assigning a reason to
`event.cancel_tool` — the tool then never runs, and the model is handed your reason
instead of a result:

```python
class AutonomyGuard(HookProvider):
    """Blocks write tools when the current decision class is not autonomous."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before_tool)

    def _before_tool(self, event: BeforeToolCallEvent) -> None:
        name = _tool_name(event)
        if not name or name in READ_ONLY:
            return                       # reading the handbook is always allowed

        decision_class = current_class()
        if not decision_class:
            # Fail closed. No established class means no writes, full stop.
            event.cancel_tool = (
                "BLOCKED: no decision class established for this message. "
                "Hand this to the Coordinator."
            )
            return

        if POLICY.may_act_alone(decision_class):
            return

        tier = POLICY.tier_of(decision_class)
        event.cancel_tool = (
            f"BLOCKED by Autonomy Dial: '{decision_class}' is at tier '{tier.value}'. "
            f"You may not call '{name}' yourself. Summarise the situation and your "
            f"recommendation for the Coordinator instead."
        )
```

(That's the shape of it. In the repo the two assignments go through a small helper that
reads `cancel_tool` back after setting it and raises if it didn't take — because if a
future SDK version renames that attribute, a silent no-op would let the write through
unguarded, which is the exact outcome the whole system exists to prevent. A crashed run is
recoverable; a permission check that quietly stopped working is not.)

The difference is categorical. A prompt is a request to a model. This is a control in the
execution path. You can ask the model very nicely to send the reply anyway, and the tool
call is still cancelled, at the SDK layer, before any state changes.

And because it's a real control, you can **test** it. The test I'm proudest of runs the
live model twice against the same message:

```
Guardrail (live model)
  [PASS] guard blocked at least one write tool
  [PASS] roster was not mutated
  [PASS] nothing was written to the ledger
  [PASS] same request succeeds once the class is AUTO

19 passed, 0 failed
```

Same model. Same message. Same words. The only thing that changed between the two runs is
permission. That's the difference between a guardrail and a promise.

Triage gets scored the same way. Every message in the scenario carries a ground-truth
label the agent never sees, and a second script checks the run against it — 24 out of 24
on the last three weeks I ran, including the four cases the scenario exists to trap: the
home-canned jam that reads like a routine donation, the crisis worded politely, the
cancellation that quietly drops Saturday below minimum staffing, and a severe allergy
sitting in a pile of five routine substitutions.

---

## The graph, and the one thing that nearly broke it

Switchboard is a Strands `GraphBuilder` graph with conditional edges:

```
                  ┌──────────────────────────────┐
  message ──────► │  TRIAGE                      │
                  │  read-only: search_handbook  │
                  │  emits {decision_class, ...} │
                  └───────────────┬──────────────┘
                                  │
                     POLICY.may_act_alone(class)?
                                  │
                 ── yes ──────────┴────────── no ──
                     │                          │
                     ▼                          ▼
          ┌────────────────────┐    ┌──────────────────────┐
          │ RESOLVER           │    │ ESCALATOR            │
          │ full toolset,      │    │ read-only. Builds a  │
          │ writes state.      │    │ Decision Desk card.  │
          │ Every call passes  │    │                      │
          │ the AutonomyGuard. │    │                      │
          └────────────────────┘    └──────────────────────┘
```

Triage classifies. The edge condition consults the policy. One branch acts; the other
researches and stops.

Now, the bug that taught me something.

My first version of the guard would never have fired. Not "fired incorrectly" — *never
fired at all*. The decision class was seeded into a `ContextVar` before the graph started
and updated after triage, and the guard read it from there. In my tests the guard passed
because I set the class manually. In a real run it was always empty.

The reason is worth knowing if you're building on Strands: the SDK may execute a graph
node on a worker thread or in a fresh task, and each of those gets a **copy** of the
current context. A `ContextVar` you set inside an edge condition is not reliably visible
to the node that runs next.

The fix is unglamorous and correct. The class lives in a module-level dict keyed by
message id:

```python
# Triage's verdict, keyed by message id.
#
# This deliberately does NOT live in the ContextVar. The class is only known
# *after* the triage node runs, and a ContextVar set inside a graph edge
# condition is not reliably visible to the node that runs next - Strands may
# execute nodes on a worker thread or a fresh task, each of which gets a *copy*
# of the context. A plain dict keyed by message id is visible everywhere, and
# single-key assignment is atomic under the GIL, which is all the safety we need.
CLASSIFICATION: dict[str, str] = {}
```

And it gets written from the edge condition, because the edge condition is the first
moment in the entire run where the class exists at all:

```python
def classify(state) -> str:
    data = parse_json(node_text(state, "triage"))
    cls = data.get("decision_class", "")
    cls = cls if cls in VALID_CLASSES else ""
    set_classification(message_id, cls)   # publish where the guard can see it
    return cls
```

If your safety control depends on state crossing an async or threading boundary, go and
check it actually arrives. Mine didn't, and every test I had was green.

---

## Two more things I'd have got wrong

**The model editorialising about its own escalations.** For one card the escalator agent
wrote: *"This was not escalated — it is a routine substitution within our standard
authority."* It was escalated. It was sitting on the coordinator's desk as it said so.

That's exactly the confident wrongness the product exists to prevent, and the fix was to
take the model out of the loop entirely. The reason a human is looking at a card is a
*fact about the policy*, not an opinion. So it's derived:

```python
if tier is Tier.NEVER:
    why = cls.rationale
else:
    why = (f"{cls.rationale} You haven't delegated this class yet — "
           f"{cls.approvals} of {cls.threshold} approvals so far.")
```

Anything the user must be able to trust should be computed, not generated. Generate the
prose around it.

**I nearly reached for a vector store.** It would look better on a slide. It would be
worse here.

The entire promise of a Decision Desk card is that a coordinator can read the quoted
clause and check the agent's work in four seconds. Lexical retrieval over headed sections
returns the section she already knows by number — *§4.2 Items we never accept* — and
returns the same section every time for the same question. Semantic search returns
something defensible and slightly different each time, which is worse for an audit trail
and no better for a corpus of ten sections she wrote herself.

Auditability beat recall. That tradeoff is written into a comment in the code, where the
decision lives, so the next person doesn't "improve" it by accident.

---

## What it looks like running

The screen has two halves and one strip.

Left is **The Desk**: only what needs a person. Right is **What it handled**: everything
it did without one, live, with the real tool calls visible as they fire. The strip along
the bottom is the dial itself — green, amber, red, with the approval counter on each amber
chip.

A week is twenty-four messages, run four at a time. It takes about sixty seconds. On a
typical run the agent handles eleven alone and puts thirteen in front of the coordinator.

That ratio is not a great headline number, and I want to be straightforward about it:
week one, this thing hands you thirteen decisions. That's the honest starting point. The
interesting number is what happens to it after a month of teaching — after the routine
dietary substitutions have been promoted, and the best-by date questions, and the
perishable donations. The classes that will still be there on the desk in a year are the
five that can never leave it, which is precisely the design intent.

The goal state of the product is an empty left panel. It should just take a while to get
there, and it should never get all the way.

---

## The part I'd want someone else to take

If you build agents for organisations that serve people — clinics, shelters, schools,
legal aid, anything where the downside of a wrong autonomous action lands on someone who
was already having a bad week — I think the dial generalises.

Three claims, in order of how much I'd argue for them:

1. **Autonomy should be per-decision-class, not per-agent.** "Can it act autonomously" is
   the wrong granularity. Nobody wants a blanket answer to that question.

2. **Autonomy should be earned from observed agreement, and lost the moment a human has
   to correct you.** Reset, not decay. An edit is the strongest signal you'll ever get
   that the agent hadn't understood the thing.

3. **Some classes must be structurally undelegatable.** Not "high threshold" — no path.
   If a sufficiently good track record could unlock the class where a person in crisis is
   waiting, you have built a system that will eventually get there.

The third one is the one I'd hold the line on. There's a real temptation, when your agent
is performing well, to let the numbers decide everything. But the question "should a
machine handle this?" isn't always a question about accuracy. Sometimes a person is the
point.

---

Switchboard is MIT licensed and the code is on GitHub. It runs on the Strands Agents SDK
against Amazon Bedrock — Claude Haiku 4.5 in `us-east-1`, deliberately the cheap tier,
because an agent that runs somebody's inbox all day has to be affordable for an
organisation that counts cans.

Clone it, point it at your own handbook, and set your own dial.
