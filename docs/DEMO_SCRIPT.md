# Switchboard — demo video script

**Target 3:00.** Two surfaces: the pitch board carries the idea, the console proves it.

| | |
|---|---|
| Pitch board | https://switchboard-one-azure.vercel.app |
| Console | https://switchboard-t7wx.onrender.com |

---

## Who is watching

AWS and Strands engineers, plus community judges, scoring on impact, technical execution,
creativity and how well the demo lands. They watch these back to back, and by video ten
every project sounds the same. Assume three things:

**They decide in the first fifteen seconds** whether this is another chatbot with a nice
font. So the opening is a real person's inbox, not an architecture slide.

**They have seen a hundred agents that act.** They have seen almost none that decline to
act. The moment that separates this project is the agent asking permission and the red
classes it can never be promoted into — spend your seconds there, not on tool calls.

**Half of them will not have AWS credentials handy** when they open your links. That is
why the console is deployed and the pitch board is static.

Two vocabulary rules for the narration. Say **permission**, not "hook" or "guardrail",
until 2:35 — then name the mechanism once, precisely, because the technical judges are
waiting for it. And never say "the model decided": the whole claim is that policy decides
and the model works inside it.

---

## Before you hit record

```bash
# 1. Wake the console — free instances sleep after 15 minutes
curl -s https://switchboard-t7wx.onrender.com/api/health
# expect: {"ok":true,"provider":"bedrock", ... "live":true}

# 2. Clear the week. The promotion beat only works from a clean dial.
curl -s -X POST https://switchboard-t7wx.onrender.com/api/reset \
  -H 'Content-Type: application/json' -d '{}'
```

Open exactly two tabs, in this order, and never type a URL on camera:

1. the pitch board
2. the console

Switch with `Ctrl`+`Tab`. Browser at **1440×900**, full screen, no bookmarks bar, no
extensions, notifications silenced. Have a terminal ready but hidden — you cut to it once,
at 2:35, so bump its font size now.

---

## The script

Format: **DO** is the action, **SAY** is word for word.

### 0:00 – 0:22 · The inbox — pitch board, hero

**DO** Start at the top of the pitch board, motionless. Let the headline hold for two
seconds before you speak. At 0:12 scroll slowly to the four messages so each verdict tag
— *answered alone*, *brought to her*, *never automatic* — lands as you name it.

**SAY**
> Riverside Community Pantry feeds four hundred households a week with one paid
> coordinator. Her actual job isn't food. It's a hundred and fifty messages a week.
>
> Are you open today — that one has an answer, in the handbook she wrote herself.
> Forty jars of homemade chutney — that needs her, and not for the reason you'd think.
> A fourteen-year-old asking to volunteer, and a mother who ran out of formula last
> night — those two should never be automatic. Ever.
>
> She spends the week on the first kind, so she reaches the last kind tired.

---

### 0:22 – 0:44 · The idea — pitch board, "autonomy is a dial"

**DO** Scroll to **The idea: autonomy is a dial, not a switch**. Stop with all three
cards — Auto, Ask, Never — in frame. Do not scroll while talking.

**SAY**
> So the question isn't *can an agent do this work*. It's *how does an agent earn the
> right to do this work*.
>
> Switchboard sorts every message into a decision class, and every class sits at one of
> three positions. Green, it acts alone and tells her afterwards. Amber, it researches,
> drafts, recommends — and stops. Red, it will never act alone, however well it performs.

---

### 0:44 – 1:06 · The picture — pitch board, architecture

**DO** Scroll to **How a message moves through it**. Hold on the whole diagram for three
seconds, then trace with the cursor: Triage → the diamond → the black GUARD box → back
along the dashed loop → stop on the red ✕ and the ceiling box.

**SAY**
> Every message goes through triage, then through the dial. If the class is green it goes
> to the resolver, and every single thing the resolver tries to do passes through this —
> a permission check that cancels the call before it runs.
>
> If it isn't green, it goes to the escalator, which researches it and builds a card for
> her, but cannot touch anything.
>
> And this dashed line is the interesting one. Three clean approvals and the agent asks
> to be promoted. Except here — *(cursor on the ✕)* — where that path doesn't exist at all.

---

### 1:06 – 1:14 · Cut to the console

**DO** `Ctrl`+`Tab`. Let the idle console sit for two seconds — empty desk, provider chip
reading `bedrock · anthropic.claude-haiku-4-5`. At 1:12 click **Run the week**.

**SAY**
> That's the design. Here it is against a real week — twenty-four messages, live, on
> Bedrock.

---

### 1:14 – 1:42 · The week runs

**DO** Hands off the mouse. Record the full run, then **speed it to 2× in the edit** and
narrate over it. Do not cut away — watching it work is the proof.

**SAY**
> Four at a time. Those chips under each message are real tool calls — searching the
> handbook, booking shifts, registering households, sending replies. Every green check is
> something that never reached her desk.

*(Stop talking for six seconds. Let it run.)*

> And everything stacking up on the left is something it decided it shouldn't do alone.

**DO** Hold until the counters settle: **11 handled alone · 13 sent to you · ~60s**.

---

### 1:42 – 2:06 · The two cards that make the case

**DO** Scroll the left panel to the **home-canned jam** card (Ronnie Pike). Scroll slowly
enough to read. Point at the quoted handbook clause at the bottom of the card.

**SAY**
> This is the one I'd point at. Forty jars of her mother's chutney, offered warmly, no red
> flags in the tone at all. State health code forbids it outright.
>
> It caught that, and look at what it hands back: why it stopped, what it recommends,
> three real options, a reply drafted to be kind about it — and the handbook clause it
> relied on, quoted, so she can check its work in about four seconds.

**DO** Scroll one card further, to **infant out of formula** (Tue 17:36).

**SAY**
> And this one it will never touch. A family in crisis gets a person. That isn't a
> confidence threshold it might cross on a good day — it's a ceiling.

---

### 2:06 – 2:35 · It asks for the promotion

**DO** Point at the footer strip and its `0/3` counters. Then approve the three **Routine
dietary substitution** cards one at a time, about a second apart, without editing them.
The dark panel rises on the third.

**SAY**
> Which brings me to the part I actually care about. Down here is the dial, live, per
> class — and it moves by being earned.
>
> Three dietary substitutions. I approved all three without changing a word. Watch.

*(Let the panel sit. Read it aloud, slowly.)*

> *"You've approved my last three routine dietary substitution recommendations without
> changing a word. Want me to start handling these myself?"*
>
> It asked. It didn't assume.

**DO** Click **Yes, handle these**. Point at the chip turning green.

**SAY**
> And if I'd edited any one of those, the count doesn't pause — it resets to zero. If she
> had to fix the answer, it hadn't learned the thing yet.

---

### 2:35 – 2:52 · It's a control, not a prompt — cut to terminal

**DO** Cut to the terminal. The command is already typed; press Enter on the cut.

```bash
python scripts/test_guard.py
```

Hold on the last four PASS lines and `19 passed, 0 failed` for a full two seconds.

**SAY**
> All of that would be theatre if the rule lived in a prompt. It doesn't. It's a Strands
> hook on `BeforeToolCall`, and it cancels the tool call before it executes.
>
> This hands the agent a message whose class is set to never, and checks the write was
> blocked and nothing was written. Then it flips that same class to auto and sends the
> identical request — and now it goes through. Same model, same message, same words. The
> only thing that changed is permission.

---

### 2:52 – 3:00 · Close

**DO** Cut back to the console, dial visible in frame. Hold two seconds after the last
word, then cut.

**SAY**
> Strands Agents on Bedrock. Nobody hands their inbox to an agent on day one. They hand
> over hours questions, watch for a week, and hand over one more thing.

---

## Trims and extensions

**To reach 2:00**, cut in this order: the architecture beat (0:44–1:06), then the second
card (the formula card, 1:58–2:06), then shorten the run to 15 seconds at 3×. Never cut
the promotion.

**If you have 4:00**, add after 2:52: demote a class back to Ask from the footer chip to
show the dial moves both ways, and show `scripts/score_week.py` printing `24/24 correct`
against labels the agent never sees.

---

## If it goes wrong on the take

| Problem | What to do |
|---|---|
| Console takes 40s to load | It was asleep. Stop, wait for it, re-run the health check, start again. |
| A message errors mid-run | Keep going. "One failed, and it went to her desk — which is the right failure." It's a genuinely good moment. |
| Promotion doesn't fire | You edited a card instead of approving, or the week wasn't clean. Reset, re-run, approve three without touching the draft. |
| Run is slower than 60s | Fine. Fix it in the edit, not on the take. |
| Provider chip shows "No model credentials found" | The server has no Bedrock key. Check the env var on Render. |

## Checklist

- [ ] Console awake and `"live":true`
- [ ] Week cleared immediately before recording
- [ ] Two tabs open in order, pitch board first
- [ ] 1440×900, full screen, no bookmarks bar, notifications off
- [ ] Terminal ready and hidden, command pre-typed, font enlarged
- [ ] Mic test — the narration carries this, not the visuals
- [ ] Export, then watch it once on mute: the story should still read
- [ ] Upload public or unlisted, and confirm the length against the rules
