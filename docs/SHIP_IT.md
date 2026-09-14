# Ship it — every command, in order

You handle the logins (GitHub, YouTube, Devpost, Render). Everything else is below,
copy-paste ready. Run all of it from the repo root: `/mnt/i/Programs/awshackathon`.

---

## 1. Push to GitHub

The repo is already initialised, committed, and on `main`. `gh` isn't installed on this
machine, so create the repo in the browser — it takes 20 seconds.

**In the browser:** go to <https://github.com/new>

- Repository name: `switchboard`
- Description: `An operations agent that runs a small food pantry's inbox — and earns the right to act alone, one decision class at a time.`
- **Public**
- Do **not** add a README, .gitignore, or license (you already have all three)

Then, in the terminal:

```bash
cd /mnt/i/Programs/awshackathon
git remote add origin https://github.com/YOUR_USERNAME/switchboard.git
git push -u origin main
```

**Make the license visible in the About sidebar** (the hackathon checks for this).
GitHub detects `LICENSE` automatically — after the push, reload the repo page and confirm
**MIT License** appears in the right-hand sidebar. If it doesn't:

```bash
# Occasionally GitHub misses detection on a file without an extension.
git mv LICENSE LICENSE.md && git commit -m "Make the license detectable" && git push
```

**Add the topics** (Devpost judges skim these). On the repo page click the ⚙ next to
"About" and paste:

```
strands-agents amazon-bedrock aws claude ai-agents human-in-the-loop nonprofit fastapi python agents-for-humans
```

---

## 2. Record the video

The script is in [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) — word for word, with the shot list
and timings. Before you hit record:

```bash
# Reset to a clean dial. The promotion beat only works from a clean run.
curl -s -X POST http://127.0.0.1:8000/api/reset

# Confirm you are live on Bedrock
curl -s http://127.0.0.1:8000/api/health
# want: {"ok":true,"provider":"bedrock", ... "live":true}
```

If the server isn't running:

```bash
cd /mnt/i/Programs/awshackathon
( set -a; . "$HOME/.claude-profiles/aws.env"; set +a; PY=$HOME/sbvenv/bin/python ./run.sh )
```

Upload to YouTube as **public or unlisted** (not private — judges must be able to open
it). Title:

```
Switchboard — an AI agent that earns the right to act alone | Agents for Humans Hackathon
```

---

## 3. Deploy the live demo (Render, free tier)

Render reads `$PORT` and `run.sh` already honours it, so there is nothing to change.

**In the browser:** <https://dashboard.render.com/> → **New** → **Web Service** → connect
your `switchboard` repo.

| Field | Value |
|---|---|
| Runtime | Python 3 |
| Build command | `pip install -r requirements.txt` |
| Start command | `python -m uvicorn switchboard.server:app --host 0.0.0.0 --port $PORT` |
| Instance type | Free |

Then **Environment** → **Add Environment Variable**:

| Key | Value |
|---|---|
| `AWS_BEARER_TOKEN_BEDROCK` | *your Bedrock API key* |
| `AWS_REGION` | `us-east-1` |

> Use a Bedrock API key scoped to Bedrock invoke only — not your root keys. Nothing
> secret is in the repo, and it must stay that way.

Once it's live, verify from your terminal:

```bash
curl -s https://YOUR-APP.onrender.com/api/health
# want: "provider":"bedrock" and "live":true
```

> **Free-tier caveat:** Render spins the instance down after 15 minutes idle, and the
> cold start takes ~40 seconds. Open your demo link and press **Run the week** once,
> about five minutes before a judge is likely to look at it. If it's asleep when they
> arrive they'll see a blank page and assume it's broken.

---

## 4. Submit on Devpost

Everything to paste is in [`SUBMISSION.md`](SUBMISSION.md) — project name, tagline, tags,
and the full "About the project" write-up.

Fill in the three links at the bottom of that file first:

- Repository: `https://github.com/YOUR_USERNAME/switchboard`
- Live demo: `https://YOUR-APP.onrender.com`
- Video: your YouTube URL

**Submission checklist:**

- [ ] Public GitHub repo, MIT license visible in the About sidebar
- [ ] Video public/unlisted, under 5 minutes
- [ ] Live demo URL responding, and warmed up
- [ ] Uses the Strands Agents SDK — say so explicitly in the description (it's already in the text)
- [ ] Screenshot uploaded (`docs/screenshot.png`)
- [ ] Blog post published and linked (see below — worth up to +0.6)

---

## 5. The bonus blog post (+0.6)

Publish [`BLOG_POST.md`](BLOG_POST.md) to <https://builder.aws.com/> — sign in, then
**Write an article**. The title already contains "Agents for Humans", which is the
requirement. Paste the markdown in directly; builder.aws.com accepts it.

Then add the published URL to your Devpost submission, in the description, near the top.

---

## Re-running the tests before you submit

```bash
cd /mnt/i/Programs/awshackathon
( set -a; . "$HOME/.claude-profiles/aws.env"; set +a;
  $HOME/sbvenv/bin/python scripts/test_guard.py )
# want: 19 passed, 0 failed
```

```bash
( set -a; . "$HOME/.claude-profiles/aws.env"; set +a;
  $HOME/sbvenv/bin/python scripts/smoke.py )
```
