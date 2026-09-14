# Switchboard — demo video script

**Target length: 3:20. Hard cap 5:00.**
Record at **1440×900**, browser in full screen, no bookmarks bar, no notifications.

---

## Before you hit record

```bash
# 1. Fresh state — this matters, the promotion beat only works from a clean dial
curl -s -X POST http://127.0.0.1:8000/api/reset

# 2. Confirm you are live on Bedrock, not a fallback
curl -s http://127.0.0.1:8000/api/health
# expect: {"ok":true,"provider":"bedrock", ... "live":true}
```

Have a second terminal open and ready on the repo root — you'll need it once, at 2:35.

---

## Shot list + word-for-word narration

### 0:00 – 0:22 · The problem (idle screen, no clicks)

**On screen:** the idle console. "An empty desk is the goal." Do not move the mouse.

> Riverside Community Pantry feeds four hundred households a week. It's run by one paid
> coordinator. And her actual job, most weeks, isn't food — it's a hundred and fifty
> messages. Are you open Saturday. Can I take the sort shift. My mum has forty jars of
> homemade jam to donate. We ran out of food yesterday and the baby finished the last
> formula this morning.
>
> Most of those already have an answer, written down in her handbook. A few of them don't.
> And she spends the week on the first kind, so she gets to the second kind tired.

---

### 0:22 – 0:40 · The thesis (still idle; hover the left panel heading)

> This is Switchboard. It reads the pantry's inbox. Left side is the only thing that needs
> her. Right side is everything it handled without her. The goal of the product is an
> empty left panel.

**Action at 0:38:** click **Run the week**.

---

### 0:40 – 1:20 · The week runs (let it breathe — do not narrate over the whole thing)

**On screen:** messages stream into the right panel, trace chips light up under each one —
`search handbook`, `book volunteer shift`, `send reply` — and green checks land. Cards
start stacking on the left.

> Twenty-four messages, four at a time. Those little chips are the real tool calls, live
> — it's searching the handbook, booking shifts, registering households, sending replies.
> Every green check is something that never reached her desk.

*(Pause for ~8 seconds. Let the viewer watch it work.)*

> And every one of these — *(gesture left)* — is something it decided it shouldn't do
> alone.

**Wait for the run to finish.** Counter should read roughly **11 handled alone / 13 sent
to you / ~64s**.

---

### 1:20 – 1:55 · The card that proves the point

**Action:** scroll the left panel to the **home-canned jam** card (Ronnie Pike). Scroll
slowly enough to read.

> Here's the one I'd point at. A woman offers forty jars of her mother's homemade
> chutney. It reads like a routine donation — friendly, generous, no red flags in the
> tone at all. State health code forbids it outright.
>
> Switchboard caught it, and look at what it hands back: why it stopped, what it
> recommends, three real options, a drafted reply that's kind about it — and the handbook
> clause it's relying on, quoted. She can check its work in four seconds.

**Action:** scroll one card further, to **"Infant out of formula"** (Anonymous, Tue 17:36).

> And this one it will never touch. A family in crisis gets a person. That's not a
> confidence threshold — it's a ceiling.

---

### 1:55 – 2:35 · The Autonomy Dial (the actual idea)

**Action:** point at the footer strip.

> Which brings me to the part I care about. Most agent demos have one switch: on, or off.
> Switchboard has a dial, per decision class. Green it does alone. Amber it researches and
> then stops. Red it will never do, no matter how well it performs.
>
> And it moves along that dial by earning it.

**Action:** approve the three **Routine dietary substitution** cards, one at a time, ~1s
apart. On the third, the dark panel rises.

> Three dietary substitutions. I approved all three without changing a word. Watch.

*(Let the modal sit on screen and read it aloud, slowly.)*

> *"You've approved my last three routine dietary substitution recommendations without
> changing a word. Want me to start handling these myself?"*
>
> It asked. It didn't assume.

**Action:** click **Yes, handle these**. Point at the chip moving from amber to green.

> And if I'd edited any one of those, the counter doesn't pause — it resets to zero. If I
> had to fix its answer, it hadn't learned the thing yet.

---

### 2:35 – 3:05 · It's a real control, not a prompt (cut to terminal)

**Action:** cut to the second terminal. Run:

```bash
.venv/bin/python scripts/test_guard.py
```

**On screen:** the PASS lines scroll; hold on the last four.

> Now — everything I just showed you would be theatre if the rule lived in a prompt. It
> doesn't. It's a Strands hook on `BeforeToolCall`, and it cancels the tool call before it
> executes.
>
> This test hands the agent a message whose class is set to never, and checks the write was
> blocked, the roster wasn't touched, the ledger is empty. Then it flips that same class to
> auto and sends the identical request — and now it goes through. Same model, same message.
> The only thing that changed is permission.

*(Hold on **`19 passed, 0 failed`** for a full two seconds.)*

---

### 3:05 – 3:20 · Close (cut back to the console)

> Strands Agents on Bedrock, three nodes, eight tools, a guard hook, and about sixty
> seconds for a week's inbox.
>
> Nobody hands their inbox to an agent on day one. They hand over hours questions, watch
> for a week, and hand over one more thing. That's the whole product.

**Final frame:** the console with the dial visible. Hold 2 seconds. Cut.

---

## If something goes wrong on the take

| Problem | What to do |
|---|---|
| A message errors mid-run | Keep going. Say "one failed — it went to her desk, which is the right failure." It is a genuinely good moment. |
| Promotion doesn't fire | You edited a card instead of approving it, or the run was already dirty. `POST /api/reset`, re-run, approve cleanly. |
| Run is slower than 64s | Fine. Trim in the edit, not on the take. |
| `provider` shows `replay` | Credentials aren't in the server's environment. Restart with the env sourced — see README. |

## Recording checklist

- [ ] `POST /api/reset` run immediately before recording
- [ ] `/api/health` shows `"provider":"bedrock"`, `"live":true`
- [ ] Browser at 1440×900, full screen, no extensions visible
- [ ] Notifications silenced
- [ ] Second terminal open at the repo root, font size bumped for legibility
- [ ] Mic test — the narration carries this, not the visuals
- [ ] Video is **public or unlisted**, and under 5:00
