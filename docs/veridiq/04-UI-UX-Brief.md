# VERIDIQ — UI/UX Design Brief

> Status labels: **[CURRENT]**, **[PHASE 5]**, **[PLANNED]**, **[OUT OF V1]**.
> This document describes an **existing, already-polished brand system**. It is a constraint document, not a blank-slate design exploration — any new screen must match these tokens and rules exactly.

## 1. Design Philosophy

VERIDIQ is an **enterprise console**, not a consumer app or a "vibe-coded mega-menu." Every screen should feel like a serious operations tool a compliance officer or ops lead would trust: dark, glass-panelled, data-dense but legible, calm rather than gamified. Concretely:

- No confetti, no fake progress bars that never finish, no chat-bubble "the AI is thinking…" theatrics.
- Numbers must be real or explicitly blank/"—" — never a placeholder that looks like data (see §6 Honesty Rules).
- Motion is subtle (180ms ease transforms on hover/press) — not a primary interaction driver.

## 2. Brand Tokens **[CURRENT — do not modify without a design decision]**

Source of truth: `veridiq/__init__.py` (`COLORS`) and `frontend/src/index.css` (`:root`).

| Token | Hex | CSS var | Usage |
|---|---|---|---|
| Deep Black | `#05070F` | `--deep-black` | Base app background. |
| Midnight Blue | `#0B1224` | `--midnight-blue` | Background gradient stop, glass panel base (`--glass: rgba(11,18,36,0.72)`). |
| Electric Blue | `#4F8CFF` | `--electric-blue` | Primary accent — links, active nav, primary gradient, focus rings. |
| Neon Purple | `#B14DFF` | `--neon-purple` | Secondary accent — paired with electric blue in gradients (`.btn-primary`, hero glows). |
| White | `#F7F9FC` | `--white` | Primary text color on dark backgrounds. |
| Soft Gray | `#9AA6BF` | `--soft-gray` | Muted/secondary text (`.muted`). |
| Danger | `#FF5C7A` | `--danger` | Failed/error states. |
| Success | `#3DD68C` | `--success` | Completed/ok states. |
| Warning | `#F5C542` | `--warning` | Degraded/pending states. |

**Semantic mapping (keep consistent everywhere a status is shown):**
- `ok` / `completed` / `sent` / `dialed` → success green.
- `configuration_required` / `queued_for_approval` / `approved_pending_integration` / `draft_only` → warning amber (this is "not an error," just "needs a human or a key").
- `error` / `failed` / `unavailable` / `rejected_by_user` → danger red.
- `working` / `processing` → electric blue accent, with the live progress affordance from §5.

## 3. Typography **[CURRENT]**

- Primary font: **Outfit** (`--font: "Outfit", "Segoe UI", sans-serif`) for all UI text.
- Monospace: `--mono: "JetBrains Mono", ui-monospace, monospace` — reserve for IDs, hashes, job UUIDs, wallet addresses, code-like values (use the `.mono` utility class).
- No serif fonts anywhere in the console.

## 4. Layout & Navigation **[CURRENT]**

- **Shell:** `AppShell.tsx` — fixed left sidebar (`.side.glass`) + main content area (`.main`). Sidebar collapses to an off-canvas drawer (`.side-open` / `.side-backdrop`) below a mobile breakpoint, toggled by a hamburger button.
- **Sidebar structure:** brand block (logo + "VERIDIQ" + "Enterprise console" subtitle) → searchable nav (`side-search` filters nav items live) → six nav groups (**Overview, Intelligence, AI Organization, Domains, Outputs, System**) → footer tagline "Truth. Verified. Empowered."
- **Do not** flatten the six nav groups into one long list, and do not add a "mega-menu" style dropdown — the grouped, searchable sidebar *is* the intended enterprise IA. New pages must be slotted into one of the existing six groups (or a new, clearly-scoped seventh group if genuinely orthogonal — get a product decision before adding one).
- **Page header pattern:** every page uses `AppShell`'s `title` + optional `subtitle` + optional `actions` (top-right buttons) — keep this consistent; don't build one-off page headers.
- **Icons:** simple inline SVG stroke icons (`ICON_PATHS` in `AppShell.tsx`), 1.8 stroke-width, `currentColor` — match this style for any new nav icon rather than importing an icon library (no icon library dependency currently exists; adding one is a **[PLANNED]** decision, not assumed).

## 5. Core UI Patterns **[CURRENT — reuse these, don't reinvent]**

| Pattern | Component/class | Rule |
|---|---|---|
| Glass panel | `.glass` | Any card/panel/sidebar surface: `background: var(--glass)`, `border: 1px solid var(--glass-border)`, `backdrop-filter: blur(18px)`, `border-radius: 16px`. |
| Metric tile | `<Metric label value hint tone>` (`AppShell.tsx`) | Small stat card; `tone` = `ok`/`bad`/`warn` maps to the semantic colors in §2. Use for dashboard/ops KPIs. |
| Idle banner | `<StatusBanner waiting label idleText>` | Renders a pulsing-dot "Waiting for Assignment" (or custom `idleText`) banner whenever `waiting` is true or `label` matches a known idle string. **Always use this component for idle states instead of a bespoke message** — consistency matters more than novelty here. |
| Empty state | `<EmptyState title body action?>` | Standard empty-list/empty-page pattern with an optional CTA. |
| Agent avatar | `<AgentAvatar name hue size>` | Gradient circle keyed by the agent's `avatar_hue` (from `identities.py`) + first-letter initial — this is the *only* avatar style; no photo avatars (personas are explicitly AI, not real people). |
| Primary button | `.btn.btn-primary` | Electric-blue → neon-purple gradient, white text, soft glow shadow. Use for the one primary action per view (Verify, Approve, Submit). |
| Secondary/ghost button | `.btn.btn-ghost` | Low-emphasis actions (Cancel, secondary nav toggles). |
| Form field | `.field` | Dark input with soft-gray border, electric-blue focus ring. |

## 6. Honesty Rules (Non-Negotiable UX Constraints) **[CURRENT product requirement]**

These come directly from the backend's design intent (`veridiq/integrations/activity.py`, `workforce/pool.py`, `workforce/roster.py` docstrings) and must be mirrored exactly in the UI:

1. **Idle agents show "Waiting for Assignment"** — not "Idle," not a spinner, not a fabricated "reviewing…" state. This exact phrase is the product's idle-label convention (`idle_label` field returned by multiple endpoints).
2. **Empty queues/logs render as empty**, with an `EmptyState`, never a skeleton that implies data is coming when the backend has already returned an empty array.
3. **Unconfigured integrations show `configuration_required`** with a clear call-to-action (which env var / where to get a key) — never hide the platform or show a fake "connected" badge.
4. **No fabricated activity feed entries.** The Collaboration Hub and Platform Activity feeds must show "No activity yet" (backend literally returns this note string) when empty — do not backfill with sample/demo rows in production builds.
5. **Confidence/score fields that are `null`** (e.g. `average_confidence` with zero completed jobs) render as `—` or "No data yet," never as `0%` (which implies a real, poor result).
6. **Approval-gated actions are visually distinct pre- and post-approval** — a `draft_only` comms draft or a `queued_for_approval` call campaign must never look identical to a `sent`/`dialed` one (color + label, per §2 semantic mapping).

## 7. Dashboard Composition Rules **[CURRENT, carried from prior polish pass]**

- Lead with **quick-action tiles** (the 8 `quick_actions` from `/dashboard`) above the fold — these are the primary navigation reinforcement for an enterprise user who wants to jump straight to a task.
- Group KPI metrics by domain (Jobs, Workforce, Market, System) rather than one long undifferentiated grid.
- Department rollups (from `department_snapshot()`) should show **live worker count and success rate**, not just a department name — the value of the "AI Organization" framing is operational visibility, not just an org chart.
- Collaboration preview on the dashboard should be a small, recent-only slice (8–12 items) linking out to the full Collaboration Hub — dashboards summarize, they don't replace the detail page.
- Never show more than one "primary" call-to-action per page — actions battle for attention in a console meant for fast scanning, not exploration.

## 8. Responsive Behavior **[CURRENT]**

- Sidebar becomes an off-canvas drawer with backdrop + Escape-to-close + scroll-lock (`AppShell.tsx` `useEffect`) below the mobile breakpoint.
- Content grids should collapse to single-column on narrow viewports; metric tiles wrap naturally via flex/grid — no fixed-width panels that would force horizontal scroll on a laptop screen.

## 9. Accessibility Notes **[CURRENT baseline / PLANNED audit]**

- `aria-label`s already present on the mobile nav toggle, close button, and search input (`sr-only` label).
- Focus rings are visible (`.field:focus` box-shadow) — preserve this on any new custom input.
- Color contrast for `--soft-gray` (`#9AA6BF`) on `--deep-black` should be checked (**[PLANNED]** formal contrast audit) before using it for anything other than secondary/muted text.

## 10. What NOT to Do

- Do not introduce a second color palette, a light mode, or a different font "for one page" — brand consistency is a hard requirement across all 20+ pages.
- Do not add decorative fake-activity widgets (ticking counters, randomly-incrementing "agents online" numbers) anywhere — this directly contradicts the Honesty Rules (§6) that differentiate VERIDIQ from typical AI-agent demo products.
- Do not replace the grouped sidebar with a top mega-nav or a command-palette-only navigation model — the sidebar IA is intentional for an enterprise console used daily, not a marketing site.
- Do not add a UI for actions that aren't backed by a real endpoint yet (e.g. a "Deploy to Mainnet" button) without also wiring the approval/role gates described in the App Flow and TRD — a visible-but-non-functional or unsafely-functional button is worse than no button.
