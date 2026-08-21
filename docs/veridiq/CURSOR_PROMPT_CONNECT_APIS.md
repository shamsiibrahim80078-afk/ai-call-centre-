# Cursor prompt: connect more official APIs into VERIDIQ

Paste this prompt into Cursor when you obtain additional platform / AI API credentials.
It tells the agent how to extend VERIDIQ safely without rebuilding the app.

---

## Task

Extend VERIDIQ to integrate new AI/platform providers as official HTTP API connectors.
Do **NOT** rebuild the existing app. **EXTEND only**.

## CRITICAL SECURITY

- User may paste LIVE API keys in chat. Put them **ONLY** in local `.env` (must be gitignored — verify `.gitignore` includes `.env`).
- **NEVER** commit keys. **NEVER** write keys into source code, tests, docs, or `.env.example`.
- In `.env.example` use empty placeholders only + docs URLs.
- In any report, **REDACT** keys (show only first 4 + last 4 chars, or `"SET"`).
- Tell the user they **must rotate all keys** after the session if they were exposed in chat.

## Implementation pattern (match `veridiq/integrations/`)

1. Create connector module(s) under `veridiq/integrations/` (prefer one file per provider, or a clean package such as `veridiq/integrations/llm/`).
2. Each connector must expose:
   - `status()` via `status_shape` from `veridiq.integrations.base`
   - `test_connection()` that hits a **cheap** official endpoint (models list / whoami / tiny auth check)
   - One minimal usable action (e.g. `generate_text`, `transcribe`, `send_message`) that requires an **explicit** call
3. Use `first_env(...)` for primary env var + optional aliases.
4. Missing credentials → `configuration_required` (never fabricated success).
5. Prefer light HTTP `test_connection` calls. Do **not** download huge models in CI. Optional local pipelines (e.g. Hugging Face `transformers`) must be opt-in via env flag and documented as optional.

## Wiring (required)

- Register status entries in `veridiq/integrations/registry.py` (new category such as `"ai"` / `"speech"` is fine).
- Add to `TEST_FUNCS` for live `/test` routes.
- Wire `PLATFORM_ACTIONS` + `MODULE_ALIASES` in `veridiq/integrations/platform_api.py`.
- Agents call via SDK: `executeTool("platform.action", ...)` which dispatches through `platform_api`.
- HTTP callers use `/api/v1/veridiq/platforms/{platform}/{action}` (same dispatch layer).
- Update `.env.example` with empty placeholders + official docs URLs.
- Merge keys into existing `.env` **without wiping** other vars (Telegram, X, etc.).
- Add focused tests (`tests/test_<area>.py`):
  - `configuration_required` when env cleared
  - status shape + registry listing + platform_api wiring
  - live `test_connection` may hit network — make resilient (`ok` / `error` / `configuration_required`)
- Run focused pytest only.

## Env var naming

Prefer `VERIDIQ_<PROVIDER>_API_KEY` (or `VERIDIQ_HF_TOKEN` / provider-standard names already used in the codebase). Document aliases in `first_env` when useful (e.g. `GOOGLE_API_KEY`).

## Return report (to parent / user)

- Files changed
- Which providers `test_connection` returned `ok` vs failed (**redact** secrets)
- How agents call via `executeTool` / `platforms/{p}/{action}`
- Reminder to **rotate** any keys pasted in chat

---

## Example agent calls after wiring

```text
sdk.executeTool("groq.status")
sdk.executeTool("groq.test")
sdk.executeTool("groq.generate_text", prompt="ping")

sdk.executeTool("deepgram.status")
sdk.executeTool("deepgram.transcribe", audio_url="https://example.com/audio.wav")

# AI Gateway (fallback across configured LLM providers)
sdk.executeTool("ai_gateway.status")
sdk.executeTool("ai_gateway.generate", prompt="ping", task_type="fast")

# Research fan-out (Tavily + Exa + SerpAPI when configured)
sdk.executeTool("research.multi_search", query="market signals")
sdk.executeTool("tavily.search", query="...")
sdk.executeTool("exa.search", query="...")
sdk.executeTool("serpapi.search", query="...")
sdk.executeTool("notion.search_pages", query="...")
```

HTTP:

```text
GET  /api/v1/veridiq/platforms
POST /api/v1/veridiq/platforms/mistral/test
POST /api/v1/veridiq/platforms/mistral/generate_text   # body: {"prompt":"..."}
POST /api/v1/veridiq/platforms/ai_gateway/generate    # body: {"prompt":"...","task_type":"fast"}
POST /api/v1/veridiq/platforms/tavily/search          # body: {"query":"..."}
```

## Optional bridges (do not replace existing auth)

- **Clerk**: connector/status + optional JWT verify stub only. FastAPI JWT remains primary. Do not rebuild a separate Clerk Next.js app.
- **Supabase**: needs `VERIDIQ_SUPABASE_URL` + `VERIDIQ_SUPABASE_ANON_KEY` (never invent the anon key).
- **Stripe**: requires `sk_test_` / `sk_live_` (or `pk_`). Non-matching values go in `VERIDIQ_STRIPE_KEY_RAW` as `configuration_required`.
- **Firebase**: project id alone is insufficient; service account required for Admin SDK.
