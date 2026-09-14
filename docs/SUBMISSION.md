# Devpost submission — copy/paste

---

## Project name

```
Switchboard
```

## Tagline (short description)

```
An operations agent that runs a small food pantry's inbox — and earns the right to act alone, one decision class at a time.
```

## Built with (tags)

```
strands-agents, amazon-bedrock, claude, python, fastapi, server-sent-events, aws, vanilla-js, multi-agent, human-in-the-loop
```

---

## "About the project" — paste into the Devpost description field

### Inspiration

Riverside Community Pantry feeds about 400 households a week, and it is run by one paid
Coordinator plus a rota of volunteers. That Coordinator's actual job turns out not to be
food. It's the inbox — roughly 150 messages a week:

> *"are you open saturday"* · *"can I sign up for the sort shift"* · *"my mum makes
> amazing chutney, shes got about 40 jars she wants to donate"* · *"i dont know if this
> is the right number. we ran out of food yesterday and the baby finished the last
> formula this morning"*

Most of those have an answer already written down in the volunteer handbook. A handful do
not, and those are the ones that matter. The Coordinator spends the week on the first
kind and arrives at the second kind exhausted.

The obvious fix — "put an AI on the inbox" — is the one small nonprofits rightly refuse.
The failure mode isn't a wrong answer about opening hours. It's an agent that cheerfully
accepts 40 jars of home-canned jam (illegal under state health code), or sends a chirpy
auto-reply to a mother who just ran out of infant formula, or strikes up a conversation
with a 15-year-old about volunteering. Those mistakes aren't measured in tokens.

So the question we actually wanted to answer was not *"can an agent do this work?"* It
was **"how does an agent earn the right to do this work?"**

### What it does

Switchboard reads the whole week's inbox. For each message it triages it into one of 16
decision classes — judging by substance, not tone — and checks that class against the
**Autonomy Dial**, a live, human-owned trust setting.

If the class is **AUTO**, it acts: searches the handbook, books the shift, registers the
household, records the donation, sends the reply, and writes what it did to a ledger.

If the class is **ASK** or **NEVER**, it stops — and does the research anyway. It hands
the Coordinator a **Decision Desk card**: what was asked, why it stopped, what it
recommends, two or three real options, a drafted reply, and the handbook clauses it
relied on, quoted, so a human can check its work in four seconds.

The screen has exactly two halves. Left is **The Desk**: only what needs a person. Right
is **What it handled**: everything it did without one, live, as it happens. The goal state
of the product is an empty left panel.

A full week — 24 messages, 4 at a time — runs in about 60 seconds. On our runs the agent
handles 11 alone and puts 13 in front of the Coordinator.

### The Autonomy Dial

Most agent demos have one switch: on, or off. Switchboard has a dial with three positions
per decision class, and the agent moves along it by earning trust.

- **AUTO** — acts alone, tells you afterwards.
- **ASK** — researches and recommends, then stops. A human decides.
- **NEVER** — will never act alone here, no matter how well it performs.

An ASK class becomes AUTO only after the Coordinator has approved the agent's
recommendation **three times without changing a word**. Then the agent asks, in its own
words:

> *You've approved my last 3 "Routine dietary substitution" recommendations without
> changing a word. Want me to start handling these myself?*

Two rules keep this honest rather than decorative:

**Editing resets the counter to zero.** Not pauses — resets. If you had to fix the
agent's answer, it hadn't learned the thing yet.

**NEVER is a ceiling, not a default.** Five classes are permanently non-promotable no
matter how many approvals pile up: a minor asking to volunteer, a severe or anaphylactic
allergy, a household in crisis, a complaint or incident, and press or a public official.
These are the situations where a human being is the entire point. The agent cannot be
talked into them — and neither can a hand-edited policy file, because the loader
re-clamps any persisted tier back under its ceiling on startup.

### How we built it

**Strands Agents SDK on Amazon Bedrock**, Claude Haiku 4.5 in us-east-1.

Orchestration is a Strands `GraphBuilder` graph with conditional edges:

```
triage ──┬── class is AUTO  ──► resolver (full toolset, writes state)
         └── class is ASK/NEVER ──► escalator (read-only, builds the card)
```

The interesting detail is that the edge condition is the first moment in the run where the
decision class exists at all, so it does double duty: it parses triage's JSON, validates
the class against the known set, and publishes it where the tools and the guard can both
see it before the next node starts.

**The guardrail is a real control, not a prompt.** `AutonomyGuard` is a Strands
`HookProvider` on `BeforeToolCallEvent`. Every write tool — booking, cancelling,
registering, referring, recording, substituting, replying — passes through it. If the
message's class is not currently AUTO, the guard calls `event.cancel_tool(...)` and the
tool never executes. It fails closed: if no class was established at all, every write is
cancelled. Ask the model nicely to send the reply anyway and the call is still cancelled,
at the SDK layer, before any state changes.

`scripts/test_guard.py` proves it with a live model — same message, class at NEVER
(write blocked), then the identical request with the class at AUTO (write succeeds).
19 assertions, all passing.

The live trace is a `TraceCollector` hook on the node and tool lifecycle, draining a
thread-safe deque onto an async event bus every 50 ms and out over SSE. The front end is
vanilla HTML/CSS/JS with no build step — deliberately, so there is nothing to go wrong on
stage.

### Challenges we ran into

**Getting the class to the guard in time.** Strands may run a graph node on a worker
thread or a fresh task, and each gets a *copy* of the current context — so a `ContextVar`
set inside an edge condition is not reliably visible to the node that runs next. Our first
version of the guard would never have fired: it read a class that was seeded empty before
the graph started and never updated. The fix is a module-level dict keyed by message id.
Single-key assignment is atomic under the GIL, which is all the safety this needs, and it
is visible from every thread in the process.

**The model editorializing about its own escalations.** For one ASK-tier card the
escalator wrote "This was not escalated — it is a routine substitution within our standard
authority," which was both wrong and exactly the kind of confident wrongness the product
exists to prevent. The reason a human is looking at a card is a fact about the policy, not
an opinion of the model, so `why_escalated` is now derived deterministically from the
policy store and the model no longer gets a vote.

**Concurrency bugs that only appear under load.** Running 4 messages at once surfaced a
reply-extraction routine that scanned the global ledger for the most recent "Replied"
entry — which, under concurrency, frequently belonged to somebody else's conversation.

**A misclassification we refused to paper over.** Home-canned jam kept landing in
"bulk donation." The tempting fix was to change the ground-truth label to match the
output. Instead we added the class the domain actually needs — `donation_homemade`, the
thing the handbook forbids outright — because the taxonomy was wrong, not the model.

### What we learned

Retrieval quality is not the same as retrieval usefulness. We started to reach for a
vector store and stopped: the entire promise of the Decision Desk is that a Coordinator
can read the quoted clause and check the agent's work in seconds. Lexical retrieval over
headed sections returns the section they already know by number — §4.2 Items we never
accept — and returns the same section every time for the same question. Auditability beat
recall, and we wrote the tradeoff into a comment where the decision lives.

The broader thing: *the safety feature and the product are the same feature.* The Autonomy
Dial is the guardrail and it is also the only reason anyone would adopt this. Nobody hands
their inbox to an agent on day one. They hand over hours questions, watch for a week, and
hand over one more thing.

### What's next for Switchboard

**Real inbox adapters** — the scenario file is a stand-in for Gmail/Twilio intake, and
nothing above the adapter changes.

**Per-organization handbooks** — the handbook is a markdown file, so onboarding a second
pantry is a file, not a fine-tune.

**Shared dials** — a pantry network could publish a recommended starting dial, including
the NEVER floor, so a new org inherits five years of someone else's hard lessons on day
one. That's the part that doesn't scale by adding GPUs, and it's the part that would
actually help.

---

## Repository

```
https://github.com/<YOUR_USERNAME>/switchboard
```

## Live demo

```
<YOUR_DEMO_URL>
```

## Video

```
<YOUR_YOUTUBE_URL>
```
