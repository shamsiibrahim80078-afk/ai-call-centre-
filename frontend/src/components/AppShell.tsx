import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Link, NavLink } from "react-router-dom";
import AuthNav from "./AuthNav";

type NavItem = { to: string; label: string; end?: boolean };
type NavGroup = { label: string; icon: string; items: NavItem[] };

const NAV_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    icon: "grid",
    items: [
      { to: "/", label: "Home", end: true },
      { to: "/dashboard", label: "Dashboard", end: true },
    ],
  },
  {
    label: "Intelligence",
    icon: "scan",
    items: [
      { to: "/dashboard/runtime", label: "Live Agent Runtime" },
      { to: "/dashboard/verify", label: "Verification Center" },
      { to: "/dashboard/investigation", label: "Investigation Center" },
      { to: "/dashboard/requests", label: "AI Requests" },
    ],
  },
  {
    label: "AI Organization",
    icon: "users",
    items: [
      { to: "/dashboard/workforce", label: "Workforce" },
      { to: "/dashboard/integrations", label: "Platform Integrations" },
      { to: "/dashboard/collaboration", label: "Collaboration Hub" },
      { to: "/dashboard/ops", label: "Operations Center" },
      { to: "/dashboard/command-center", label: "Command Center" },
    ],
  },
  {
    label: "Domains",
    icon: "globe",
    items: [
      { to: "/dashboard/market", label: "Market Intelligence" },
      { to: "/dashboard/meeting", label: "Meeting Intelligence" },
      { to: "/dashboard/news", label: "News Intelligence" },
      { to: "/dashboard/comms", label: "Comms Assistant" },
      { to: "/dashboard/calling", label: "AI Calling" },
      { to: "/dashboard/postings", label: "Postings" },
      { to: "/dashboard/marketing", label: "Marketing Agency" },
    ],
  },
  {
    label: "Outputs",
    icon: "file",
    items: [
      { to: "/dashboard/reports", label: "Reports" },
      { to: "/dashboard/jobs", label: "Jobs" },
      { to: "/dashboard/blockchain", label: "Blockchain" },
      { to: "/dashboard/launchpad", label: "Token Launchpad" },
    ],
  },
  {
    label: "System",
    icon: "gear",
    items: [
      { to: "/dashboard/account", label: "Account" },
      { to: "/dashboard/settings", label: "Settings" },
    ],
  },
];

const ICON_PATHS: Record<string, string> = {
  grid: "M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z",
  scan: "M9 3H5a2 2 0 0 0-2 2v4m18 0V5a2 2 0 0 0-2-2h-4M3 15v4a2 2 0 0 0 2 2h4m10 0h-4a2 2 0 0 1 0-4h4a2 2 0 0 0 2-2v-4",
  users:
    "M17 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 5 18.5V20m14 0v-1.5a3 3 0 0 0-2-2.83M15 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3.7 5.67A3 3 0 0 0 17 8",
  globe:
    "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0 0c-2 0-3.6-4-3.6-9S10 3 12 3s3.6 4 3.6 9-1.6 9-3.6 9ZM3.5 9h17M3.5 15h17",
  file: "M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm7 0v5h5",
  gear: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm8-3a7.97 7.97 0 0 0-.2-1.8l2-1.5-2-3.4-2.3.9a8 8 0 0 0-3-1.75L14 2h-4l-.5 2.45a8 8 0 0 0-3 1.75l-2.3-.9-2 3.4 2 1.5A7.97 7.97 0 0 0 4 12c0 .61.07 1.2.2 1.8l-2 1.5 2 3.4 2.3-.9a8 8 0 0 0 3 1.75L10 22h4l.5-2.45a8 8 0 0 0 3-1.75l2.3.9 2-3.4-2-1.5c.13-.6.2-1.19.2-1.8Z",
  menu: "M4 6h16M4 12h16M4 18h16",
  close: "M6 6l12 12M18 6 6 18",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10 2-4.35-4.35",
};

function Icon({ name, size = 16 }: { name: string; size?: number }) {
  const d = ICON_PATHS[name];
  if (!d) return null;
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden focusable="false">
      <path d={d} stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

type AppShellProps = {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
};

export default function AppShell({ title, subtitle, actions, children }: AppShellProps) {
  const [navQ, setNavQ] = useState("");
  const [mobileOpen, setMobileOpen] = useState(false);

  const groups = useMemo(() => {
    const q = navQ.trim().toLowerCase();
    if (!q) return NAV_GROUPS;
    return NAV_GROUPS.map((g) => ({
      ...g,
      items: g.items.filter((i) => i.label.toLowerCase().includes(q)),
    })).filter((g) => g.items.length > 0);
  }, [navQ]);

  useEffect(() => {
    if (!mobileOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMobileOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [mobileOpen]);

  return (
    <div className="app-shell dash enterprise">
      {mobileOpen ? <div className="side-backdrop" onClick={() => setMobileOpen(false)} aria-hidden /> : null}

      <aside className={`side glass ${mobileOpen ? "side-open" : ""}`} aria-label="Primary">
        <div className="side-top">
          <Link to="/" className="side-brand" onClick={() => setMobileOpen(false)}>
            <img src="/veridiq-logo.svg" alt="" width={34} height={34} />
            <div>
              <strong>VERIDIQ</strong>
              <span className="muted">Enterprise console</span>
            </div>
          </Link>
          <button
            type="button"
            className="side-close"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation"
          >
            <Icon name="close" />
          </button>
        </div>

        <label className="side-search">
          <span className="sr-only">Filter navigation</span>
          <Icon name="search" size={15} />
          <input
            className="side-search-input"
            placeholder="Search navigation…"
            value={navQ}
            onChange={(e) => setNavQ(e.target.value)}
          />
        </label>

        <nav className="side-nav">
          {groups.length === 0 ? (
            <p className="muted side-nav-empty">No matches for “{navQ}”.</p>
          ) : (
            groups.map((group) => (
              <div key={group.label} className="nav-group">
                <p className="nav-group-label">
                  <Icon name={group.icon} size={13} />
                  <span>{group.label}</span>
                </p>
                {group.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={Boolean(item.end)}
                    onClick={() => setMobileOpen(false)}
                    className={({ isActive }) => (isActive ? "nav-item active" : "nav-item")}
                  >
                    <span className="nav-item-label">{item.label}</span>
                  </NavLink>
                ))}
              </div>
            ))
          )}
        </nav>

        <p className="side-tag muted">Truth. Verified. Empowered.</p>
      </aside>

      <main className="main">
        <header className="main-head">
          <button
            type="button"
            className="side-toggle btn btn-ghost"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Icon name="menu" />
          </button>
          <div className="main-head-text">
            <p className="eyebrow">VERIDIQ</p>
            <h1>{title}</h1>
            {subtitle ? <p className="muted page-sub">{subtitle}</p> : null}
          </div>
          <div className="main-actions">
            {actions}
            <AuthNav />
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}

export function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "ok" | "bad" | "warn";
}) {
  return (
    <div className={`metric glass ${tone ? `metric-${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint ? <em>{hint}</em> : null}
    </div>
  );
}

export function StatusBanner({
  waiting,
  label,
  idleText = "Waiting for Assignment",
}: {
  waiting?: boolean;
  label?: string;
  idleText?: string;
}) {
  const show =
    waiting ||
    label === "Waiting for Tasks" ||
    label === "Waiting for Assignment" ||
    label === idleText;
  if (!show) return null;
  return (
    <div className="waiting-banner glass" role="status">
      <span className="waiting-dot" aria-hidden />
      {idleText}
    </div>
  );
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p className="muted">{body}</p>
      {action}
    </div>
  );
}

export function AgentAvatar({
  name,
  hue = 210,
  size = 40,
  presentation,
  hair,
  skin,
  hairColor,
  roleHint,
}: {
  name: string;
  hue?: number;
  size?: number;
  presentation?: string;
  hair?: string;
  skin?: string;
  hairColor?: string;
  roleHint?: string;
}) {
  const present = (presentation || "androgynous").toLowerCase();
  const hairStyle = (hair || "short").toLowerCase();
  const face = skin || `hsl(${hue} 35% 62%)`;
  const hairFill = hairColor || `hsl(${(hue + 20) % 360} 40% 18%)`;
  const feminine = present === "feminine";
  const masculine = present === "masculine";
  const uid = `av-${(name || "a").replace(/\W/g, "").slice(0, 8)}-${hue}-${size}`;
  const role = (roleHint || "").toLowerCase();
  // Subtle role tint only — cohesive system, not clipart badges
  let accentHue = hue;
  if (/market|growth|campaign|brand/.test(role)) accentHue = 210;
  else if (/influencer|creator outreach|relations/.test(role)) accentHue = 350;
  else if (/content|canva|poster|social|copy/.test(role)) accentHue = 45;
  else if (/ops|director|ceo|orchestr/.test(role)) accentHue = 195;

  // Distinct silhouette: hair path + soft features (not letter circles)
  let hairPath = "M18 38 C22 18, 78 18, 82 38 L78 42 C70 24, 30 24, 22 42 Z"; // short
  if (hairStyle === "long" || hairStyle === "waves") {
    hairPath = feminine
      ? "M16 36 C20 12, 80 12, 84 36 L86 78 C78 70, 70 74, 66 58 L60 40 L40 40 L34 58 C30 74, 22 70, 14 78 Z"
      : "M18 34 C24 14, 76 14, 82 34 L84 62 C76 54, 70 50, 66 40 L34 40 C30 50, 24 54, 16 62 Z";
  } else if (hairStyle === "bun") {
    hairPath = "M38 16 C38 8, 62 8, 62 16 C62 22, 38 22, 38 16 Z M18 40 C24 18, 76 18, 82 40 L76 44 C68 26, 32 26, 24 44 Z";
  } else if (hairStyle === "fade") {
    hairPath = "M22 42 C26 22, 74 22, 78 42 L74 40 C68 28, 32 28, 26 40 Z";
  } else if (hairStyle === "pixie") {
    hairPath = "M20 40 C28 16, 72 14, 80 38 L72 36 C64 22, 36 24, 28 38 Z";
  }

  const jaw = feminine ? "M28 52 C30 78, 70 78, 72 52" : masculine ? "M26 50 C28 80, 72 80, 74 50" : "M27 51 C29 78, 71 78, 73 51";

  return (
    <div
      className="agent-avatar agent-avatar-face"
      style={{
        width: size,
        height: size,
        background: `linear-gradient(160deg, hsl(${accentHue} 42% 36%), hsl(${(accentHue + 28) % 360} 38% 22%))`,
      }}
      aria-hidden
      title={name}
    >
      <svg viewBox="0 0 100 100" width={size} height={size} role="presentation">
        <defs>
          <clipPath id={`${uid}-clip`}>
            <circle cx="50" cy="50" r="46" />
          </clipPath>
        </defs>
        <g clipPath={`url(#${uid}-clip)`}>
          <circle cx="50" cy="54" r="28" fill={face} />
          <path d={hairPath} fill={hairFill} />
          <path d={jaw} fill={face} opacity="0.35" />
          <ellipse cx="38" cy="52" rx="3.2" ry={feminine ? 3.6 : 3.1} fill="#1a1520" />
          <ellipse cx="62" cy="52" rx="3.2" ry={feminine ? 3.6 : 3.1} fill="#1a1520" />
          <path
            d={feminine ? "M42 64 Q50 70 58 64" : "M43 65 Q50 68 57 65"}
            fill="none"
            stroke="#5a4038"
            strokeWidth="2"
            strokeLinecap="round"
          />
          {feminine ? (
            <path d="M30 56 Q26 62 30 66" fill="none" stroke={face} strokeWidth="3" opacity="0.55" />
          ) : null}
          {masculine ? <rect x="46" y="58" width="8" height="3" rx="1" fill={hairFill} opacity="0.35" /> : null}
        </g>
        <circle cx="50" cy="50" r="47" fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth="1.5" />
        <circle cx="50" cy="50" r="49" fill="none" stroke={`hsla(${accentHue}, 55%, 55%, 0.35)`} strokeWidth="1" />
      </svg>
    </div>
  );
}
