# Travel Planner — public web app for your Claude Managed Agent

A chat page anyone can open in a browser. It talks to your Travel Planner agent on the
Claude Platform. Visitors don't need a Claude account; usage is billed to your API credits.

```
travel-agent-app/
├── app.py                          backend (holds your API key, streams the agent's reply)
├── static/index.html               chat page
├── setup_agent.py                  one-time: creates the agent + environment, prints IDs
├── travel-agent-system-prompt.md   the agent's instructions
├── requirements.txt
└── render.yaml                     one-click deploy config for Render
```

## Step 1 — Get your API key and agent IDs (5 min)

1. In Claude Console, go to **API keys** → create a key. Copy it (starts with `sk-ant-`).
2. Add a few dollars of credit under **Billing**.
3. Get an **Agent ID** and **Environment ID**, either way:
   - **Already built the agent in Console?** Open it under Managed Agents and copy both IDs.
     Make sure web search is enabled for it.
   - **Otherwise**, run the setup script on your computer (needs Python 3.10+):
     ```bash
     pip install anthropic
     export ANTHROPIC_API_KEY=sk-ant-...      # Windows PowerShell: $env:ANTHROPIC_API_KEY="sk-ant-..."
     python setup_agent.py
     ```
     It prints `AGENT_ID=...` and `ENVIRONMENT_ID=...`. The agent gets only web search and
     web fetch, nothing else.

## Step 2 — Deploy to Render (free tier, 10 min)

1. Push this folder to a new GitHub repository (private is fine).
2. Go to [render.com](https://render.com) → **New → Blueprint** → pick the repo.
   Render reads `render.yaml` and creates the web service.
3. When asked, fill in the environment variables (your Agent and Environment IDs are already set in `render.yaml`):
   - `ANTHROPIC_API_KEY` — your key
   - `ACCESS_CODE` — optional. Set it to share the app only with people who know the code;
     leave empty for fully public.
4. Deploy. Your app is live at `https://travel-planner-xxxx.onrender.com`.
   Open `/healthz` on that URL — `{"ok": true}` means the variables are set.

Free Render services sleep after ~15 minutes idle, so the first visit afterwards takes
about a minute to wake up. The paid starter plan removes that.

**Other hosts** work the same way (Railway, Fly.io, a VPS): install `requirements.txt`,
set the same environment variables, and run
`uvicorn app:app --host 0.0.0.0 --port $PORT`.

## Run it on your own computer first (optional)

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in the values, then:
export $(grep -v '^#' .env | xargs)
uvicorn app:app --reload
```
Open http://localhost:8000.

## Protecting your credits

A public page means strangers spend your API credits. Built-in protections:

- **Per-conversation spend cap** — `SESSION_BUDGET_USD` (default $3). Your test plan cost $1.26.
- **Per-visitor limit** — `MAX_MESSAGES_PER_HOUR` (default 5) per IP address.
- **Access code** — set `ACCESS_CODE` to require a code.
- **Message length** capped at 2,000 characters; each turn times out after 10 minutes.
- **Tools** — the agent can only search and read the web. If it ever asks permission for any
  other tool, the server denies it.

Also set a **monthly spend limit** in Console → Billing → Limits. That's your hard ceiling.

**Rough cost per trip plan:** tokens + web searches ($10 per 1,000 searches) + session runtime
($0.08 per running hour). A plan typically runs 10–20 searches, so searches alone are about
$0.10–0.20. Run a few test trips and check Console → Usage before sharing widely.

## Changing the agent's behaviour

Edit `travel-agent-system-prompt.md`, then update the agent's system prompt in Console
(or create a new agent with `setup_agent.py` and swap the `AGENT_ID` on Render).
No redeploy of the web app is needed for prompt changes made in Console.
