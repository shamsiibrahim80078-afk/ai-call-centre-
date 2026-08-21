# VERIDIQ Telegram Mini App

Simple English + short Urdu notes. Mini App = **website inside Telegram**. Bot long-poll worker is **separate**.

## Kya cheez hai? (What is it?)

Telegram Mini App = a normal HTTPS web page that opens **inside** Telegram when the user taps the bot **Menu** button (or an inline `web_app` button).

| Piece | Role |
|--------|------|
| **Frontend HTTPS URL** | The Mini App (Vite build / static host) |
| **Bot Menu Button** | Opens that URL via `setChatMenuButton` |
| **Telegram worker** | Long-poll / webhook — replies to messages; **not** the Mini App host |

Local `http://127.0.0.1:5173` **will not work** inside Telegram. Public **HTTPS** chahiye.

## Step-by-step

### 1) Deploy frontend (HTTPS)

Frontend only — Vercel / Cloudflare Pages / Render Static / Fly static are all fine for the Mini App.

Examples:

```bash
cd frontend
npm ci
npm run build
# Deploy `dist/` to any static HTTPS host
```

Set Vite API base if the API is on another origin:

```bash
# frontend .env / host env
VITE_API_BASE=https://YOUR_API_HOST
```

Recommended Mini App entry path: `https://YOUR_FRONTEND/mini`  
(root `/` also auto-redirects to `/mini` when opened inside Telegram.)

### 2) Env vars (backend / machine that talks to Bot API)

```env
VERIDIQ_TELEGRAM_BOT_TOKEN=...          # already used by @Shamsiibrahim_bot worker
VERIDIQ_TELEGRAM_MINIAPP_URL=https://YOUR_FRONTEND/mini
```

`VERIDIQ_TELEGRAM_MINIAPP_URL` = **frontend** URL, not the Fly/Render worker URL.

### 3) Set Menu Button (script)

```bash
python scripts/set_telegram_menu_button.py
# or explicit:
python scripts/set_telegram_menu_button.py --url https://YOUR_FRONTEND/mini --text "Open VERIDIQ"
# verify:
python scripts/set_telegram_menu_button.py --check
```

### 4) BotFather checklist (optional extra)

1. Open [@BotFather](https://t.me/BotFather)
2. `/mybots` → your bot → **Bot Settings** → **Menu Button** → **Configure menu button**
3. Set the same HTTPS URL (or rely on the script above — script is enough)
4. Optional: `/setdomain` if you use Telegram Login Widget elsewhere (not required for basic WebApp Menu)

### 5) Open in Telegram

1. Open `@Shamsiibrahim_bot` (or your bot)
2. Tap **Menu** / **Open VERIDIQ**
3. Mini App loads → console shortcuts (Dashboard / Verify / Workforce)

## What the repo adds

| Area | What |
|------|------|
| Frontend | `telegram-web-app.js` in `index.html`, `src/lib/telegramWebApp.ts`, route `/mini`, splash skip inside Telegram |
| Backend | `POST /api/v1/veridiq/telegram/webapp/auth` — validates `initData` HMAC with bot token; can issue VERIDIQ JWT |
| Status | `GET /api/v1/veridiq/telegram/miniapp` |
| Script | `scripts/set_telegram_menu_button.py` |

## Auth note

When Mini App opens, frontend sends `Telegram.WebApp.initData` to the auth endpoint. Backend checks Telegram’s HMAC (`WebAppData` + bot token). On success it can create/link a local user and return `access_token` (stored as `veridiq_token`).

## Important: do not confuse hosting

- **Mini App** = public HTTPS **frontend**
- **Telegram worker** = long-poll / webhook process (`docs/DEPLOY_TELEGRAM_FLY.md` / Render) — stays separate
- Do **not** put the Mini App on the worker dyno unless that service also serves the static frontend over HTTPS

## Quick troubleshoot

| Problem | Fix |
|---------|-----|
| Menu opens blank / fails | URL must be `https://…` and reachable from the internet |
| `hash mismatch` | Wrong bot token vs the bot that opened the WebApp |
| Auth works but API 401 | Set `VITE_API_BASE` to your API; CORS must allow the frontend origin |
| Worker replies OK but no Menu | Run `set_telegram_menu_button.py` / set BotFather Menu Button |
