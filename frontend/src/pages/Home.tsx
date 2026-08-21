import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import AuthNav from "../components/AuthNav";
import { api } from "../api/client";
import heroArt from "../assets/hero.png";

const FEATURES = [
  {
    title: "Truth Verification",
    body: "Multi-agent claim verification with confidence scoring, lie detection, and decision synthesis — backed by real evidence retrieval.",
    to: "/dashboard/verify",
  },
  {
    title: "Agent Workforce",
    body: "A live roster of specialized agents organized by department, each with identity, role, and an auditable activity history.",
    to: "/dashboard/workforce",
  },
  {
    title: "Platform Integrations",
    body: "Connect calling, comms, market intelligence, and CRM platforms — every integration reports its real configuration state.",
    to: "/dashboard/integrations",
  },
  {
    title: "Blockchain Attestation",
    body: "Anchor verification outcomes on-chain for a tamper-evident record of truth, with full transaction history.",
    to: "/dashboard/blockchain",
  },
];

function StatPill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`home-status-pill glass`}>
      <span className="live-dot" style={{ color: ok ? "var(--success)" : "var(--warning)" }} aria-hidden />
      {label}
    </span>
  );
}

/**
 * Public-facing brand entry (marketing Home). Surfaces only a high-level
 * snapshot — agent overview, campaign overview, system status — via
 * /api/v1/veridiq/home-overview. The full ops console (agent management,
 * campaign controls, logs, reports, settings) lives at /dashboard/*.
 */
export default function Home() {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .homeOverview()
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const brand = data?.brand || {};
  const agents = data?.agents || {};
  const verification = data?.verification || {};
  const campaigns = data?.campaigns || {};
  const integrations = data?.integrations || {};

  return (
    <div className="home-page">
      <nav className="home-nav">
        <div className="home-nav-brand">
          <img src="/veridiq-logo.svg" alt="" width={30} height={30} />
          <span>{brand.name || "VERIDIQ"}</span>
        </div>
        <div className="home-nav-actions">
          <AuthNav />
          <Link className="btn btn-ghost" to="/dashboard/verify">
            Verify a claim
          </Link>
          <Link className="btn btn-primary" to="/dashboard">
            Enter Dashboard
          </Link>
        </div>
      </nav>

      <section className="home-hero">
        <div className="home-hero-bg" aria-hidden />
        <div className="home-hero-layout">
          <div className="home-hero-content">
            <span className="home-eyebrow">{data ? `System ${data.system_status}` : "Enterprise truth & workforce platform"}</span>
            <h1 className="home-title">
              Verify truth. <span>Deploy an agent workforce.</span>
            </h1>
            <p className="home-subtitle">
              {brand.tagline || "Truth. Verified. Empowered."} VeriDiQ combines multi-agent claim verification with a
              live, department-organized agent workforce — connected to your real platforms, honestly reporting what
              is and isn't configured.
            </p>
            <div className="home-cta-row">
              <Link className="btn btn-primary" to="/dashboard">
                Enter Dashboard
              </Link>
              <Link className="btn btn-ghost" to="/dashboard/workforce">
                Meet the Workforce
              </Link>
            </div>

            <div className="home-status-strip">
              <StatPill ok={data?.system_status === "operational"} label={data ? `System ${data.system_status}` : "Connecting…"} />
              <StatPill ok={(agents.active ?? 0) >= 0} label={`${agents.active ?? "—"} agents active · ${agents.idle ?? "—"} waiting`} />
              <StatPill ok={(integrations.configured ?? 0) > 0} label={`${integrations.configured ?? 0}/${integrations.total ?? 0} platforms configured`} />
            </div>
          </div>
          <div className="home-hero-visual glass" aria-hidden>
            <img src={heroArt} alt="" width={520} height={520} />
          </div>
        </div>
      </section>

      <section className="home-section">
        <h2>Platform overview</h2>
        <p className="muted">A high-level snapshot — open the Dashboard for full analytics, controls, and logs.</p>
        <div className="home-overview-grid">
          <div className="home-overview-card glass">
            <strong>{agents.total ?? "—"}</strong>
            <span>Agents in the workforce</span>
          </div>
          <div className="home-overview-card glass">
            <strong>{data?.departments?.total ?? "—"}</strong>
            <span>Departments</span>
          </div>
          <div className="home-overview-card glass">
            <strong>{verification.completed ?? 0}/{verification.recent_jobs ?? 0}</strong>
            <span>Recent verification jobs completed</span>
          </div>
          <div className="home-overview-card glass">
            <strong>{campaigns.total ?? 0}</strong>
            <span>Active campaigns</span>
          </div>
        </div>
      </section>

      <section className="home-section">
        <h2>What VeriDiQ does</h2>
        <div className="home-feature-grid">
          {FEATURES.map((f) => (
            <Link key={f.title} to={f.to} className="home-feature-card glass">
              <h3>{f.title}</h3>
              <p>{f.body}</p>
            </Link>
          ))}
        </div>
      </section>

      <footer className="home-footer">
        <span>
          {brand.name || "VERIDIQ"} {brand.version ? `· v${brand.version}` : ""} — {brand.tagline || "Truth. Verified. Empowered."}
        </span>
        <Link className="mono" to="/dashboard/settings">
          Settings
        </Link>
      </footer>
    </div>
  );
}
