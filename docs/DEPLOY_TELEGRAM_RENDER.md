# Deploy VERIDIQ Telegram bot 24/7 on Render

> **Free / cheaper alternative:** Fly.io long-poll worker (no public HTTP, typically ~$2/mo or legacy free allowance) — see **[DEPLOY_TELEGRAM_FLY.md](./DEPLOY_TELEGRAM_FLY.md)**. Render Background Workers are paid (~$7 Starter).

## Why this architecture

**Recommended: Background Worker + long-poll (`getUpdates`)**

- Reuses the existing listener (`veridiq.integrations.telegram_listener`)
- No public HTTPS URL required
- Always-on on Render **Starter** (Background Workers are not free)
- Render’s network can reach `api.telegram.org` — no local VPN

**Alternative: Web Service + webhook**

- Prefer if you only want a free web service (accept cold starts)
- Telegram POSTs updates to your HTTPS URL; service registers `setWebhook` on boot
- Use when long-poll is undesirable or you already run a public web process

Run **one** inbound path only. Do not run a long-poll worker and a webhook (or a second `getUpdates` poller in FastAPI) at the same time.

The main FastAPI app (`uvicorn app:app`) is optional and separate if you want the full VERIDIQ API/dashboard online. When Telegram runs on a dedicated worker, set `VERIDIQ_TELEGRAM_LISTENER_IN_API=0` on the API service.

---

## Env vars (paste in Render Dashboard)

| Variable | Required | Notes |
|----------|----------|--------|
| `VERIDIQ_TELEGRAM_BOT_TOKEN` | **Yes** | From [@BotFather](https://t.me/BotFather) |
| `VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID` | Recommended | Channel/group id or `@username` for marketing sends |
| `VERIDIQ_TELEGRAM_AUTO_REPLY` | No (default `1`) | Inbound Q&A replies |
| `VERIDIQ_TELEGRAM_WELCOME` | No (default `1`) | Welcome `new_chat_members` |
| `VERIDIQ_TELEGRAM_REPLY_ONLY_MENTIONS` | No (default `0`) | `1` = reply only when @bot mentioned in groups |
| `VERIDIQ_TELEGRAM_MODE` | No | `longpoll` (worker) or `webhook` (web service) |
| `VERIDIQ_TELEGRAM_PROXY` | No | Only if Telegram is blocked (rare on Render) |
| `VERIDIQ_TELEGRAM_LISTENER_IN_API` | No | Set `0` on FastAPI web if worker owns updates |
| `VERIDIQ_TELEGRAM_WEBHOOK_URL` | Webhook only | Full HTTPS URL, or omit and use `RENDER_EXTERNAL_URL` |
| `VERIDIQ_TELEGRAM_WEBHOOK_SECRET` | Webhook only | Random secret; sent as `X-Telegram-Bot-Api-Secret-Token` |
| `VERIDIQ_TELEGRAM_WEBHOOK_PATH` | Webhook only | Default `/telegram/webhook` |
| `LOG_LEVEL` | No | Default `INFO` |

Aliases (optional): `TELEGRAM_BOT_TOKEN`, `BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID`, `TELEGRAM_CHAT_ID`. Prefer `VERIDIQ_*`.

BotFather: add the bot as a **group admin**. For join events under privacy mode: `/setprivacy` → **Disable**.

---

## A) Background Worker (recommended)

### Build / Start

- **Build Command:** `pip install -r requirements-telegram.txt`
- **Start Command:** `python scripts/run_telegram_worker.py`  
  (equivalent: `python -m veridiq.integrations.telegram_listener`)

### Blueprint

Repo includes [`render.yaml`](../render.yaml). In Render: **New → Blueprint** → select the repo, or create a **Background Worker** manually with the commands above.

### Dashboard steps

1. Push this repo to GitHub (commands below).
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Background Worker**.
3. Connect the GitHub repo / branch.
4. Runtime: **Python**. Region: any (Oregon is fine).
5. Build / Start as above. Plan: **Starter** (always-on).
6. **Environment** → add the env vars from the table (at least the bot token).
7. Deploy. Logs should show `Telegram listener bot identity: @...` then idle long-polls.
8. Message the bot in a group/DM — you should get an auto-reply / welcome.

---

## B) Webhook Web Service (alternative)

- **Build Command:** `pip install -r requirements-telegram.txt`
- **Start Command:** `python scripts/run_telegram_webhook.py`
- **Health Check Path:** `/healthz`

Set:

```text
VERIDIQ_TELEGRAM_MODE=webhook
VERIDIQ_TELEGRAM_WEBHOOK_SECRET=<random-long-string>
VERIDIQ_TELEGRAM_WEBHOOK_PATH=/telegram/webhook
```

On boot the service calls `setWebhook` using `VERIDIQ_TELEGRAM_WEBHOOK_URL` or `https://<your-service>.onrender.com/telegram/webhook` via `RENDER_EXTERNAL_URL`.

Uncomment the webhook service block in `render.yaml` and **disable** the long-poll worker if you switch.

---

## GitHub: commit & push (you run these)

Do **not** commit `.env` (it is gitignored). Example:

```bash
git status
git add requirements.txt requirements-telegram.txt render.yaml \
  scripts/run_telegram_worker.py scripts/run_telegram_webhook.py \
  veridiq/integrations/telegram.py veridiq/integrations/telegram_listener.py \
  veridiq/integrations/telegram_webhook_app.py \
  docs/DEPLOY_TELEGRAM_RENDER.md .env.example app.py \
  veridiq/host_assistant.py veridiq/calling/agent.py \
  tests/test_host_general_knowledge.py
git commit -m "$(cat <<'EOF'
Add Render Telegram worker deploy and harden assistant tone bans.

EOF
)"
git push -u origin HEAD
```

On Windows PowerShell you can use:

```powershell
git commit -m "Add Render Telegram worker deploy and harden assistant tone bans."
git push -u origin HEAD
```

Then connect that GitHub repo in Render as described above.

---

## Local dry-run

```bash
pip install -r requirements-telegram.txt
# With token in .env:
python -c "from veridiq.integrations.telegram_listener import listener_status; print(listener_status())"
python scripts/run_telegram_worker.py
# Ctrl+C to stop
```

Webhook dry-run:

```bash
set VERIDIQ_TELEGRAM_MODE=webhook
python scripts/run_telegram_webhook.py
# GET http://127.0.0.1:10000/healthz
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `getUpdates` conflict / 409 | Another poller or webhook is active — stop local uvicorn listener or `deleteWebhook` |
| No join welcomes | Bot admin + BotFather `/setprivacy` → Disable |
| API unreachable locally | VPN or `VERIDIQ_TELEGRAM_PROXY` — usually **not** needed on Render |
| Worker and API both polling | Set `VERIDIQ_TELEGRAM_LISTENER_IN_API=0` on the FastAPI service |
