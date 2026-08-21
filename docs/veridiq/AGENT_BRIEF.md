# Agent Brief — Read This First

If you are an AI coding agent about to work on this repository:

1. **Read `docs/veridiq/*.md` first**, in this order: `README.md` → `01-PRD.md` → `02-TRD.md` → `03-App-Flow.md` → `04-UI-UX-Brief.md` → `05-Backend-Schema.md` → `06-Implementation-Plan.md`.
2. **Do not rebuild.** VERIDIQ already has a working FastAPI backend, a 30-agent LangGraph-orchestrated verification/market pipeline, a live workforce/departments/workspace system, a polished React console (22 routes), official-API integrations, and blockchain attestation readiness. Extend the existing VERIDIQ system — do not scaffold a new app, new schema, or new design system from scratch.
3. **No fabricated live activity, ever.** Idle agents show "Waiting for Assignment." Empty queues/logs/feeds render empty. Unconfigured integrations report `configuration_required`. Never invent numbers, statuses, or activity to make the UI "look busy."
4. **Official APIs only.** Every external platform integration (news, market data, social, calling, CRM, email) must use a documented official API/OAuth flow. No scraping of third-party platforms for live product data, ever — the one existing exception (a single opt-in Playwright screenshot of a user-supplied URL) is not a precedent for anything else.
5. **Approval gates are mandatory for outbound actions.** Any feature that sends an email, dials a number, posts to social, or otherwise contacts someone/something external must follow the existing draft → explicit approve → (configured) send pattern (see App Flow §2.6). Never wire a "send" action directly to user input without this gate.
6. **Follow the Implementation Plan phases.** Check `06-Implementation-Plan.md` before starting a task — it tells you what's already done (Phases 1–4), what's actively being hardened (Phase 5: persistence + RBAC), and what's next (Phase 6+). If your task isn't there, propose where it fits rather than starting ad hoc.
7. **Check the Backend Schema doc before writing SQL.** Most tables you'd think to create probably already exist (`05-Backend-Schema.md`). Follow the existing migration pattern (`_ensure_column`, additive `CREATE TABLE IF NOT EXISTS`) rather than introducing a new ORM or database engine.
8. **Match the existing brand and UI patterns exactly** (`04-UI-UX-Brief.md`) — colors, Outfit font, glass panels, sidebar IA, existing components (`Metric`, `StatusBanner`, `EmptyState`, `AgentAvatar`). Don't introduce a new design language for "just one page."

When in doubt: grep the codebase before assuming something doesn't exist, and prefer a small, additive change over a rewrite.
