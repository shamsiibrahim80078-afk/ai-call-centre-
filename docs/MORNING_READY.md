# VeriDiQ — Morning Ready Report (overnight build)

Generated for handoff: paste API credentials into `.env`, restart backend, verify each integration.

## Telegram (`@Ibrahimshamsi_bot`)

| Check | Status |
|-------|--------|
| Code: forum `message_thread_id`, greetings, webhook clear, single listener | **Ready** |
| Proxy support (`VERIDIQ_TELEGRAM_PROXY` / `HTTPS_PROXY` / `HTTP_PROXY`) | **Ready** |
| Unit tests (`tests/test_telegram_listener.py`) | **14/14 pass** |
| Live API from this machine | **Blocked** — `api.telegram.org` SSL timeout without proxy/VPN |

**Tomorrow — Telegram vars:**
```
VERIDIQ_TELEGRAM_BOT_TOKEN=        # from @BotFather
VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID=  # @ibrahimshamsi1 or numeric group id
VERIDIQ_TELEGRAM_AUTO_REPLY=1
VERIDIQ_TELEGRAM_PROXY=            # only if Telegram API is blocked on your network
```

**Verify Telegram:**
1. `python scripts/telegram_diag_quick.py` → getMe ok, bot `@Ibrahimshamsi_bot`
2. Post in `@ibrahimshamsi1` Veridiq topic → bot auto-replies in same thread
3. `python scripts/telegram_poll.py --send-test` → message in channel/topic
4. Start backend **without** `--reload` (single getUpdates poller)

---

## Marketing Agency — feature-complete offline

| Feature | Status |
|---------|--------|
| Run marketing team now | **Ready** — bounded drafts (no flood) |
| Per-agent Run now (Renata, Jasper, Lena, Theo, Nova, Adrian) | **Ready** |
| Human voice personas (6 distinct writers, day-rotated templates) | **Ready** — no LLM, no keys |
| Content queue → Approve / Approve all (paced cadence) | **Ready** |
| Go-live checklist (send-ready env vars) | **Ready** — OAuth for X, not bearer-only |
| Live platform feed | **Ready** — drafts + `configuration_required` honestly |
| Influencer (Adrian) posts + engagement comment drafts | **Ready** — Generate Adrian reply in Advanced |
| Canva / video storyboard | **Ready** (offline generation; live render needs webhook vars) |

### Demo without any API keys

1. Start backend: `python -m uvicorn app:app --host 0.0.0.0 --port 8001`
2. Frontend: `cd frontend && npm run dev`
3. **Marketing Agency** → **Run marketing team now**
4. Content queue fills with human-voice drafts (per-agent personas)
5. **Approve** one draft → live feed shows `configuration_required` with exact missing vars (not a fake send)
6. **Approve all pending** — paced 30–180s apart when multiple drafts (set jitter to 0 in `.env` for instant tests)
7. **Advanced** → Engagement comment → **Generate Adrian reply** → Draft comment → Approve
8. **Influencer Relations** card → **Run now** — hook/CTA Instagram + X drafts
9. **Live Runtime** page — marketing agent activity + platform trail

Nothing is simulated: missing credentials always surface as `configuration_required`.

### Paste later for live sends (after demo)

**Telegram** (posts + auto-reply listener):
```
VERIDIQ_TELEGRAM_BOT_TOKEN=        # from @BotFather
VERIDIQ_TELEGRAM_DEFAULT_CHAT_ID=  # @channel or numeric group id
VERIDIQ_TELEGRAM_AUTO_REPLY=1
VERIDIQ_TELEGRAM_PROXY=            # only if api.telegram.org blocked
```

**X / Twitter** (OAuth 1.0a for posts — Bearer alone is status-only; may need paid API credits):
```
VERIDIQ_X_API_KEY=
VERIDIQ_X_API_SECRET=
VERIDIQ_X_ACCESS_TOKEN=
VERIDIQ_X_ACCESS_TOKEN_SECRET=
VERIDIQ_X_BEARER_TOKEN=            # optional status/test probe
```

**LinkedIn**:
```
VERIDIQ_LINKEDIN_CLIENT_ID=
VERIDIQ_LINKEDIN_CLIENT_SECRET=
VERIDIQ_LINKEDIN_ACCESS_TOKEN=
VERIDIQ_LINKEDIN_PERSON_URN=       # optional
```

**Instagram** (Graph API — image required on post drafts):
```
VERIDIQ_INSTAGRAM_ACCESS_TOKEN=
VERIDIQ_INSTAGRAM_USER_ID=
```

Restart backend after pasting. Re-run go-live checklist or open Integrations page to confirm send-ready.

---

## Influencer Relations (Adrian)

| Feature | Status |
|---------|--------|
| Agent identity + Run now | **Ready** |
| Hook/CTA multi-platform drafts (IG, X, LinkedIn, Telegram) | **Ready** — human_voice templates |
| Engagement comment drafts | **Ready** — `GET /marketing/comments/preview` or Generate Adrian reply |
| Live feed visibility | **Ready** — filtered on Live Runtime page |

**Verify influencer (no keys):**
1. Marketing page → Influencer Relations → **Run now**
2. Drafts contain hook/CTA / "real talk" / Adrian signoff markers
3. Advanced → Generate Adrian reply → Draft comment → Approve → `configuration_required` in feed

---

## Regression (overnight)

| Check | Result |
|-------|--------|
| `pytest tests/ -q` | **150/150 pass** |
| `npm run build` (frontend) | **Pass** |
| Backend start | `uvicorn app:app --host 0.0.0.0 --port 8001` (no `--reload`) |

---

## Quick start tomorrow

```powershell
# 1. Paste vars into .env (see .env.example bottom section)
# 2. Restart backend
cd c:\Users\hp\Desktop\work
python -m uvicorn app:app --host 0.0.0.0 --port 8001

# 3. Frontend (optional)
cd frontend
npm run dev
```

Do **not** run `scripts/telegram_poll.py` while the backend listener is active — Telegram allows only one `getUpdates` consumer.
