# Deploy VERIDIQ Telegram bot 24/7 on Fly.io

## Why Fly (not Vercel, not local VPN)

| Option | Why it fits / fails |
|--------|---------------------|
| **Fly.io Machines** | Always-on VM; outbound HTTPS to `api.telegram.org`; long-poll `getUpdates` works with **no public HTTP** and **no local VPN**. |
| **Vercel** | Serverless/ephemeral functions with short request lifetimes — **cannot** run a 24/7 long-poll loop. |
| **Render Background Worker** | Works, but **Starter is paid** (~$7/mo). See [DEPLOY_TELEGRAM_RENDER.md](./DEPLOY_TELEGRAM_RENDER.md). |
| **Local + VPN** | Quota burns; machine must stay on. |

**Confirmed model:** one Fly Machine runs `python scripts/run_telegram_worker.py`, which long-polls Telegram from Fly’s datacenter network. You do not need a VPN on your PC, and you do not need to expose a port.

Run **one** inbound path only (do not also run a local poller or a webhook for the same bot).

---

## Free / low-cost notes

- Scale to **`shared-cpu-1x` / 256MB** (already set in [`fly.toml`](../fly.toml)).
- **Legacy free allowance** (orgs still on Hobby / Launch / Scale from before Oct 2024): up to **3× shared-cpu-1x 256MB** may be covered — check [Fly pricing](https://fly.io/docs/about/pricing/) → *Legacy Free allowances*.
- **New Pay As You Go orgs:** no permanent free Machine allowance. One always-on `shared-cpu-1x` 256MB is typically **~$2/month** (region-dependent) — still far below Render’s Background Worker. New accounts may get a short **free trial credit**; a card is usually required after that.
- This worker has **no public HTTP service**, so you avoid a dedicated IPv4 charge. Outbound Telegram traffic is tiny.

Always verify current pricing and allowances in the Fly dashboard before relying on “free”.

---

## Env vars / secrets

| Variable | Required | Notes |
|----------|----------|--------|
| `VERIDIQ_TELEGRAM_BOT_TOKEN` | **Yes** | From [@BotFather](https://t.me/BotFather) — set via `fly secrets`, never commit |
| `VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID` | Recommended | Channel/group id or `@username` for marketing sends |
| `VERIDIQ_TELEGRAM_AUTO_REPLY` | No (default `1` in fly.toml) | Inbound Q&A replies |
| `VERIDIQ_TELEGRAM_WELCOME` | No (default `1`) | Welcome `new_chat_members` |
| `VERIDIQ_TELEGRAM_REPLY_ONLY_MENTIONS` | No (default `0`) | `1` = reply only when @bot mentioned in groups |
| `VERIDIQ_TELEGRAM_MODE` | No | `longpoll` (set in fly.toml) |
| `VERIDIQ_TELEGRAM_PROXY` | No | Almost never needed on Fly |
| `LOG_LEVEL` | No | Default `INFO` |
| Optional LLM keys | No | Richer auto-replies (`VERIDIQ_GROQ_API_KEY`, etc.) — same as local |

Aliases still work (`TELEGRAM_BOT_TOKEN`, `BOT_TOKEN`, …). Prefer `VERIDIQ_*`.

BotFather: add the bot as a **group admin**. For join events under privacy mode: `/setprivacy` → **Disable**.

---

## Windows PowerShell: install & deploy

### 1) Install flyctl

```powershell
# Official installer (PowerShell)
pwsh -Command "iwr https://fly.io/install.ps1 -useb | iex"
```

Close and reopen the terminal (or refresh `PATH`), then:

```powershell
fly version
```

Docs: [Install flyctl](https://fly.io/docs/flyctl/install/).

### 2) Log in

```powershell
cd c:\Users\hp\Desktop\work
fly auth login
```

### 3) Create the app (use the existing `fly.toml`)

Repo already has `Dockerfile` + `fly.toml` (`app = 'veridiq-telegram-worker'`, process `worker`, no HTTP).

**Option A — create app name from fly.toml, then deploy:**

```powershell
cd c:\Users\hp\Desktop\work
fly apps create veridiq-telegram-worker
# If the name is taken:
# fly apps create veridiq-telegram-worker-YOURSUFFIX
# then edit app = '...' in fly.toml to match
```

**Option B — interactive launch (keep existing config):**

```powershell
cd c:\Users\hp\Desktop\work
fly launch --no-deploy --copy-config --name veridiq-telegram-worker
```

Do **not** let launch add an HTTP service for this worker. If prompted for a database or Redis, skip.

### 4) Set secrets (required token; optional chat / flags)

```powershell
cd c:\Users\hp\Desktop\work

# Required — paste your real token from BotFather (do not commit it)
fly secrets set VERIDIQ_TELEGRAM_BOT_TOKEN="PASTE_TOKEN_HERE"

# Optional
fly secrets set VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID="@your_channel_or_group"
# fly secrets set VERIDIQ_TELEGRAM_AUTO_REPLY="1"
# fly secrets set VERIDIQ_TELEGRAM_WELCOME="1"
# fly secrets set VERIDIQ_TELEGRAM_REPLY_ONLY_MENTIONS="0"
```

Set multiple at once:

```powershell
fly secrets set `
  VERIDIQ_TELEGRAM_BOT_TOKEN="PASTE_TOKEN_HERE" `
  VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID="@your_channel_or_group" `
  VERIDIQ_TELEGRAM_AUTO_REPLY="1" `
  VERIDIQ_TELEGRAM_WELCOME="1"
```

### 5) Deploy

```powershell
cd c:\Users\hp\Desktop\work
fly deploy
```

### 6) Scale (confirm one always-on worker at 256MB)

```powershell
fly scale count worker=1
fly scale memory 256 --process-group worker
fly status
fly logs
```

Logs should show bot identity (`Telegram listener bot identity: @...`) then idle long-polls. Message the bot in a DM/group to verify auto-reply / welcome.

### Useful commands

```powershell
fly apps list
fly status
fly logs
fly secrets list
fly machine list
fly ssh console   # optional debug shell
fly apps destroy veridiq-telegram-worker   # teardown when done
```

---

## Files in this repo

| File | Role |
|------|------|
| [`Dockerfile`](../Dockerfile) | Python 3.12 slim; `pip install -r requirements-telegram.txt`; CMD worker |
| [`fly.toml`](../fly.toml) | Process `worker`, `shared-cpu-1x` 256MB, **no** public HTTP |
| [`requirements-telegram.txt`](../requirements-telegram.txt) | Slim deps for the bot |
| [`scripts/run_telegram_worker.py`](../scripts/run_telegram_worker.py) | Entrypoint |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `getUpdates` conflict / 409 | Stop local uvicorn / other pollers; or `deleteWebhook` if a webhook was set |
| Deploy wants HTTP health check | Remove any `[http_service]` Fly added; this app is worker-only |
| Machine exits / restarts | `fly logs`; confirm `VERIDIQ_TELEGRAM_BOT_TOKEN` is set (`fly secrets list`) |
| No join welcomes | Bot admin + BotFather `/setprivacy` → Disable |
| Still using local VPN | You can disconnect after Fly is healthy — traffic originates from Fly |

If you also deploy the full FastAPI API elsewhere, set `VERIDIQ_TELEGRAM_LISTENER_IN_API=0` on that API so only this Fly worker owns updates.
