import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import AppShell, { EmptyState, Metric, StatusBanner } from "../components/AppShell";
import LiveAgentActivity from "../components/LiveAgentActivity";
import OptionalAssistant from "../components/OptionalAssistant";
import { api } from "../api/client";
import { formatRelativeTime } from "../lib/format";

const CTA_ICONS: Record<string, string> = {
  verify: "M9 12.5 11 15l4.5-6M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0Z",
  investigation: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm10 2-4.35-4.35",
  requests: "M13 3 4 14h6l-1 7 9-11h-6l1-7Z",
  workforce: "M17 20v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 5 18.5V20m14 0v-1.5a3 3 0 0 0-2-2.83M15 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z",
  reports: "M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm7 0v5h5",
  jobs: "M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2m-9 0h12a1 1 0 0 1 1 1v10a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V8a1 1 0 0 1 1-1Z",
  market: "M4 19h16M6 15l4-5 3 3 5-7",
  default: "M13 3 4 14h6l-1 7 9-11h-6l1-7Z",
};

function ctaIcon(id: string) {
  const key = Object.keys(CTA_ICONS).find((k) => id.toLowerCase().includes(k));
  return CTA_ICONS[key || "default"];
}

const CTA_HINTS: Record<string, string> = {
  verify: "Run a new claim verification",
  investigation: "Deep-dive an active case",
  requests: "Ask the workforce directly",
  workforce: "Browse the full AI roster",
  reports: "Download generated PDFs",
  jobs: "Track verification jobs",
  market: "Live crypto & market data",
};

function ctaHint(id: string, fallback: string) {
  const key = Object.keys(CTA_HINTS).find((k) => id.toLowerCase().includes(k));
  return (key && CTA_HINTS[key]) || fallback;
}

const TEST_JOB_TITLES = new Set(["API verify", "Pipeline test", "SSE test", "attest-test"]);

function isTestJob(job: { title?: string }) {
  const title = (job.title || "").trim();
  return TEST_JOB_TITLES.has(title);
}

export default function Dashboard() {
  const [dash, setDash] = useState<any>(null);
  const [system, setSystem] = useState<any>(null);
  const [ops, setOps] = useState<any>(null);
  const [roster, setRoster] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [d, s, o, r] = await Promise.all([
        api.dashboard(),
        api.system(),
        api.ops(),
        api.workforceRoster(),
      ]);
      setDash(d);
      setSystem(s);
      setOps(o);
      setRoster(r);
    } catch (e: any) {
      setError(e.message || "Failed to load dashboard");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const workforce = dash?.workforce || ops?.workforce || {};
  const waiting = Boolean(workforce?.waiting_for_tasks);
  const recent = (dash?.jobs?.recent || []).filter((j: any) => !isTestJob(j));
  const rag = dash?.rag || system?.rag || {};
  const chain = dash?.blockchain || system?.blockchain || {};
  const quickActions = dash?.quick_actions || [];

  const activity = useMemo(
    () =>
      (roster?.cards || [])
        .filter((c: any) => c.status === "working")
        .map((c: any) => ({
          agent_type: c.agent_type,
          name: c.name,
          role: c.role,
          hue: c.avatar_hue,
          task: c.current_task,
          status_label: "Running",
        })),
    [roster]
  );

  return (
    <AppShell
      title="Dashboard"
      subtitle="Enterprise control center — live metrics, quick actions, and workforce visibility"
      actions={
        <button className="btn btn-ghost" type="button" onClick={() => void refresh()}>
          Refresh
        </button>
      }
    >
      <section className="arch-strip glass" aria-label="System health">
        <strong>System health</strong>
        <span className="health-item">
          <span className={`health-dot ${system?.database === "ok" ? "ok" : ""}`} />
          API {system?.database || "…"}
        </span>
        <span className="health-item">
          <span className={`health-dot ${dash?.agents?.langgraph?.ok ? "ok" : ""}`} />
          LangGraph
        </span>
        <span className="muted mono">RAG {rag.backend || "—"}</span>
        <span className="muted mono">chain {chain.mode || "—"}</span>
        <span className="muted mono">queue {workforce.queue_depth ?? 0}</span>
        <span className="muted mono">{system?.latency_ms ?? "—"} ms</span>
      </section>

      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} idleText="Waiting for Assignment" />

      <section className="metrics">
        <Metric label="Active workers" value={String(workforce.active_workers ?? 0)} />
        <Metric label="Running jobs" value={String(dash?.jobs?.running ?? 0)} />
        <Metric label="Completed" value={String(dash?.jobs?.completed ?? 0)} />
        <Metric
          label="Avg confidence"
          value={
            typeof dash?.jobs?.average_truth_score === "number"
              ? `${Math.round(dash.jobs.average_truth_score * 100)}%`
              : "—"
          }
        />
      </section>

      {quickActions.length > 0 ? (
        <section className="panel glass">
          <p className="section-label">Quick actions</p>
          <div className="cta-grid">
            {quickActions.map((a: any) => (
              <Link key={a.id} to={a.path} className="cta-card glass">
                <span className="cta-icon">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path
                      d={ctaIcon(a.id || a.label || "")}
                      stroke="currentColor"
                      strokeWidth={1.8}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </span>
                <strong>{a.label}</strong>
                <span>{ctaHint(a.id || a.label || "", "Jump straight into this workflow")}</span>
              </Link>
            ))}
          </div>
        </section>
      ) : null}

      <div className="dash-grid">
        <section className="panel glass">
          <div className="panel-head">
            <h2>Live workforce</h2>
            <Link className="text-link" to="/dashboard/workforce">
              View all →
            </Link>
          </div>
          <LiveAgentActivity items={activity} />
        </section>

        <section className="panel glass">
          <div className="panel-head">
            <h2>Operations</h2>
            <Link className="text-link" to="/dashboard/ops">
              View all →
            </Link>
          </div>
          <ul className="stat-list">
            <li>
              <span>Workflows running</span>
              <strong>{ops?.workflows?.running ?? 0}</strong>
            </li>
            <li>
              <span>Idle workers</span>
              <strong>{ops?.idle_workers ?? 0}</strong>
            </li>
            <li>
              <span>SSE</span>
              <strong>{ops?.sse?.status || "ready"}</strong>
            </li>
            <li>
              <span>RAG</span>
              <strong>{rag.backend || "—"}</strong>
            </li>
          </ul>
        </section>

        <section className="panel glass">
          <div className="panel-head">
            <h2>Collaboration</h2>
            <Link className="text-link" to="/dashboard/collaboration">
              Open hub →
            </Link>
          </div>
          {(dash?.collaboration_preview || []).length === 0 ? (
            <EmptyState title="No active collaboration" body="Waiting for Assignment — new agent-to-agent messages will appear here." />
          ) : (
            <ul className="assignment-list">
              {(dash.collaboration_preview || []).slice(0, 4).map((m: any) => (
                <li key={m.id}>
                  <span className="mono">{m.speaker?.name}</span>
                  <span>{m.message}</span>
                  <span className="mono">{m.kind}</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="panel glass">
          <div className="panel-head">
            <h2>Market intelligence</h2>
            <Link className="text-link" to="/dashboard/market">
              View all →
            </Link>
          </div>
          <p className="muted">Official CoinGecko + Binance public tickers. Analyses are probabilistic estimates.</p>
        </section>
      </div>

      <section className="panel glass">
        <div className="panel-head">
          <h2>Recent investigations</h2>
          <Link className="text-link" to="/dashboard/jobs">
            All jobs →
          </Link>
        </div>
        {recent.length === 0 ? (
          <EmptyState title="No recent jobs" body="Start a verification or send an AI request to see activity here." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Truth</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {recent.slice(0, 6).map((j: any) => (
                  <tr key={j.job_uuid}>
                    <td>{j.title}</td>
                    <td>
                      <span className={`pill ${j.status === "completed" ? "ok" : j.status === "failed" ? "bad" : ""}`}>
                        {j.status}
                      </span>
                    </td>
                    <td className="mono">
                      {j.truth_score != null ? `${Math.round(Number(j.truth_score) * 100)}%` : "—"}
                    </td>
                    <td className="mono muted" title={j.created_at}>
                      {formatRelativeTime(j.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <OptionalAssistant />
    </AppShell>
  );
}
