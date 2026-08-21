import { useCallback, useEffect, useRef, useState } from "react";
import AppShell, { EmptyState, Metric } from "../components/AppShell";
import { api, subscribeWorkforceEvents, type WorkforceSnapshot } from "../api/client";

const STATUS_TONE: Record<string, string> = {
  ok: "ok",
  public: "ok",
  configured: "ok",
  configuration_required: "warn",
  unavailable: "bad",
  error: "bad",
};

const SOCIAL_SEND_PLATFORMS = new Set(["x_twitter", "linkedin", "instagram", "threads"]);

function completionTone(status: string): string {
  if (status === "completed") return "ok";
  if (status === "failed") return "bad";
  if (status === "configuration_required") return "warn";
  return STATUS_TONE[status] ?? "";
}

function StatusPill({ status }: { status: string }) {
  const tone = completionTone(status);
  return <span className={`pill ${tone}`}>{status.replace(/_/g, " ")}</span>;
}

export default function IntegrationsPage() {
  const [data, setData] = useState<any>(null);
  const [activity, setActivity] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, any>>({});
  const [liveMode, setLiveMode] = useState<"connecting" | "sse" | "polling">("connecting");
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [integrations, act] = await Promise.all([api.integrations(), api.integrationsActivity({ limit: 40 })]);
      setData(integrations);
      setActivity(act.activity || []);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load integrations");
    }
  }, []);

  useEffect(() => {
    void load();
    const id = window.setInterval(() => void load(), 8000);
    return () => window.clearInterval(id);
  }, [load]);

  // Reuse the workforce SSE stream for a faster activity feed refresh.
  useEffect(() => {
    let cancelled = false;
    const stopSse = subscribeWorkforceEvents(
      (snapshot: WorkforceSnapshot) => {
        if (cancelled) return;
        setLiveMode("sse");
        if (snapshot.platform_activity) setActivity(snapshot.platform_activity);
        if (pollRef.current) {
          window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      },
      () => {
        if (cancelled) return;
        setLiveMode("polling");
      }
    );
    return () => {
      cancelled = true;
      stopSse();
    };
  }, []);

  async function runTest(platform: string) {
    setTesting(platform);
    try {
      const result = await api.integrationTest(platform);
      setTestResults((prev) => ({ ...prev, [platform]: result }));
      void load();
    } catch (e: any) {
      setTestResults((prev) => ({ ...prev, [platform]: { status: "error", message: e.message } }));
    } finally {
      setTesting(null);
    }
  }

  const integrations: any[] = data?.integrations || [];
  const categories: string[] = data?.categories || [];
  const workingCount = integrations.filter((i: any) => ["ok", "public", "configured"].includes(i.status)).length;
  const needsCredsCount = integrations.filter((i: any) => i.status === "configuration_required").length;

  return (
    <AppShell
      title="Platform Integrations"
      subtitle="Modular connectors for social, messaging, email, CRM, and market platforms — official APIs only"
      actions={
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
          <span className={`live-indicator ${liveMode === "connecting" ? "" : liveMode}`}>
            <span className="live-dot" aria-hidden />
            {liveMode === "sse" ? "Live · SSE" : liveMode === "polling" ? "Live · Polling" : "Connecting…"}
          </span>
          <button className="btn btn-ghost" type="button" onClick={() => void load()}>
            Refresh
          </button>
        </div>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}
      <div className="banner" style={{ marginBottom: "1rem" }}>
        Drafts and agent runs work offline. Social connectors show <strong>configuration required</strong> until you paste
        official API tokens — X may also need paid credits before live posts succeed.
      </div>

      <section className="metrics">
        <Metric label="Total connectors" value={String(integrations.length)} />
        <Metric label="Working / public" value={String(workingCount)} tone="ok" />
        <Metric label="Need credentials" value={String(needsCredsCount)} tone={needsCredsCount ? "warn" : undefined} />
        <Metric label="Categories" value={String(categories.length)} />
      </section>

      {categories.map((cat) => (
        <section key={cat} className="panel glass">
          <div className="panel-head">
            <h2 style={{ textTransform: "capitalize" }}>{cat.replace(/_/g, " ")}</h2>
          </div>
          <div className="worker-grid">
            {integrations
              .filter((i: any) => i.category === cat)
              .map((i: any) => {
                const testResult = testResults[i.platform];
                return (
                  <div key={i.platform} className="worker-card glass">
                    <div className="worker-card-head">
                      <div>
                        <strong>{i.display_name}</strong>
                        <span className="muted mono">{i.platform}</span>
                      </div>
                      <StatusPill status={i.status} />
                    </div>
                    <div className="worker-card-body">
                      <p>{i.message || "No additional detail."}</p>
                      {i.capabilities?.length ? (
                        <div className="skill-row" style={{ marginBottom: "0.6rem" }}>
                          {i.capabilities.map((c: string) => (
                            <span key={c} className="skill-chip">
                              {c}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {!i.configured && i.env_vars?.length ? (
                        <p className="muted" style={{ fontSize: "0.78rem" }}>
                          Env vars: <span className="mono">{i.env_vars.filter(Boolean).join(", ")}</span>
                        </p>
                      ) : null}
                      {SOCIAL_SEND_PLATFORMS.has(i.platform) && i.status === "configuration_required" ? (
                        <p className="muted" style={{ fontSize: "0.78rem", marginTop: "0.35rem" }}>
                          Live posts wait for credentials{i.platform === "x_twitter" ? " / API credits" : ""} — marketing
                          drafts queue without them.
                        </p>
                      ) : null}
                      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.6rem" }}>
                        <button
                          className="btn btn-ghost"
                          type="button"
                          disabled={testing === i.platform}
                          onClick={() => void runTest(i.platform)}
                        >
                          {testing === i.platform ? "Testing…" : "Test connection"}
                        </button>
                        {i.docs_url ? (
                          <a className="muted" href={i.docs_url} target="_blank" rel="noreferrer">
                            Docs
                          </a>
                        ) : null}
                      </div>
                      {testResult ? (
                        <p className="muted" style={{ marginTop: "0.5rem", fontSize: "0.8rem" }}>
                          <StatusPill status={testResult.status} /> {testResult.message}
                        </p>
                      ) : null}
                    </div>
                  </div>
                );
              })}
          </div>
        </section>
      ))}

      <section className="panel glass">
        <div className="panel-head">
          <h2>Live platform activity</h2>
        </div>
        {activity.length === 0 ? (
          <EmptyState
            title="No activity yet"
            body="This feed only shows real connector/integration calls — nothing is simulated. Run a verification, live market request, or a connectivity test above to see entries here."
          />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Platform</th>
                  <th>Agent</th>
                  <th>Task</th>
                  <th>Stage</th>
                  <th>Status</th>
                  <th>Finished</th>
                </tr>
              </thead>
              <tbody>
                {activity.map((a: any) => (
                  <tr key={a.id}>
                    <td>{a.platform}</td>
                    <td className="mono">{a.agent_type || "—"}</td>
                    <td>{a.recent_activity || a.task}</td>
                    <td>{a.workflow_stage || "—"}</td>
                    <td>
                      <span className={`pill ${completionTone(a.completion_status)}`}>{a.completion_status}</span>
                    </td>
                    <td className="mono muted">{a.finished_at}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </AppShell>
  );
}
