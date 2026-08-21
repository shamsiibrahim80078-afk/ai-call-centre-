import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import AppShell, { Metric, StatusBanner } from "../components/AppShell";
import { api } from "../api/client";

export default function CommandCenterPage() {
  const [cc, setCc] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [monitor, setMonitor] = useState<any>(null);
  const [platforms, setPlatforms] = useState<any>(null);
  const [cascadeBusy, setCascadeBusy] = useState(false);
  const [cascadeResult, setCascadeResult] = useState<any>(null);
  const [probeBusy, setProbeBusy] = useState(false);
  const [probeResult, setProbeResult] = useState<any>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [command, mon, plats] = await Promise.all([
        api.commandCenter(),
        api.osMonitor().catch(() => null),
        api.platforms().catch(() => null),
      ]);
      setCc(command);
      setMonitor(mon);
      setPlatforms(plats);
    } catch (e: any) {
      setError(e.message || "Failed to load command center");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(id);
  }, [refresh]);

  async function runCascade() {
    setCascadeBusy(true);
    setCascadeResult(null);
    try {
      const result = await api.osCascade("E2E readiness: directors execute one worker each and probe connectors");
      setCascadeResult(result);
      await refresh();
    } catch (e: any) {
      setCascadeResult({ ok: false, error: e.message || "Cascade failed" });
    } finally {
      setCascadeBusy(false);
    }
  }

  async function probePlatforms() {
    setProbeBusy(true);
    setProbeResult(null);
    try {
      const [gw, search] = await Promise.all([
        api.platformAction("ai_gateway", "status").catch((e: any) => ({ status: "error", message: e.message })),
        api.sdkExecuteTool("ceo", "research.multi_search", { query: "AI agents market", max_results_per_provider: 2 }).catch((e: any) => ({
          status: "error",
          message: e.message,
        })),
      ]);
      setProbeResult({ ai_gateway: gw, multi_search: search });
      await refresh();
    } catch (e: any) {
      setProbeResult({ ok: false, error: e.message || "Probe failed" });
    } finally {
      setProbeBusy(false);
    }
  }

  const wf = cc?.workforce || {};
  const workflows = cc?.workflows || {};
  const waiting = Boolean(wf.waiting_for_tasks);
  const assignments = wf.assignments || [];
  const performance = cc?.performance || {};
  const sdkTasks = monitor?.sdk_tasks || [];

  return (
    <AppShell
      title="Live Multi-Agent Command Center"
      subtitle="Real-time workers, workflows, Agent SDK cascade, and platform APIs"
      actions={
        <>
          <button className="btn btn-ghost" type="button" onClick={() => void refresh()}>
            Refresh
          </button>
          <button className="btn btn-ghost" type="button" disabled={probeBusy} onClick={() => void probePlatforms()}>
            {probeBusy ? "Probing…" : "Probe AI + search"}
          </button>
          <button className="btn primary" type="button" disabled={cascadeBusy} onClick={() => void runCascade()}>
            {cascadeBusy ? "Running cascade…" : "Run CEO → Directors cascade"}
          </button>
        </>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} label={cc?.status_label} />

      <section className="arch-strip glass">
        <strong>Live status</strong>
        <span className={`pill ${(cc?.system?.database === "ok" && "ok") || ""}`}>
          Backend {cc?.system?.database || "…"}
        </span>
        <span className="pill ok">SSE {cc?.sse?.status || "ready"}</span>
        <span className="muted mono">RAG {cc?.rag?.backend || "—"}</span>
        <span className="muted mono">latency {cc?.api_latency_ms ?? "—"} ms</span>
        <span className="muted mono">avg exec {cc?.average_execution_ms ?? "—"} ms</span>
      </section>

      <section className="metrics ops-metrics">
        <Metric label="Active workers" value={String(cc?.active_ai_workers ?? 0)} />
        <Metric label="Waiting workers" value={String(cc?.idle_workers ?? 0)} />
        <Metric label="Running workflows" value={String(workflows.running ?? 0)} />
        <Metric label="Completed" value={String(workflows.completed ?? 0)} />
        <Metric label="Failed" value={String(workflows.failed ?? 0)} />
        <Metric label="Retry / queue" value={String(cc?.retry_queue ?? wf.queue_depth ?? 0)} />
        <Metric label="Queue depth" value={String(wf.queue_depth ?? 0)} />
        <Metric label="Pool" value={`${wf.total_workers ?? 0}/${wf.max_workers ?? 50}`} />
        <Metric label="SDK tasks" value={String(sdkTasks.length)} />
        <Metric label="Platforms" value={String(platforms?.count ?? "—")} />
        <Metric label="OS working" value={String(monitor?.working ?? "—")} />
        <Metric label="OS idle" value={String(monitor?.idle ?? "—")} />
      </section>

      {cascadeResult ? (
        <section className="panel glass">
          <h2>Leadership cascade result</h2>
          <p className="muted">
            {cascadeResult.summary || cascadeResult.error || (cascadeResult.ok ? "Cascade completed" : "Cascade finished")}
          </p>
          <pre className="code-block">{JSON.stringify(cascadeResult, null, 2)}</pre>
        </section>
      ) : null}

      {probeResult ? (
        <section className="panel glass">
          <h2>Platform probe</h2>
          <p className="muted">AI Gateway status + multi_search fan-out (honest configuration_required when keys missing).</p>
          <pre className="code-block">{JSON.stringify(probeResult, null, 2)}</pre>
        </section>
      ) : null}

      <div className="dash-grid">
        <section className="panel glass">
          <div className="panel-head">
            <h2>Current assignments</h2>
            <Link className="text-link" to="/dashboard/collaboration">
              Hub →
            </Link>
          </div>
          {assignments.length === 0 ? (
            <p className="muted waiting-copy">Waiting for Tasks</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Worker</th>
                    <th>Agent</th>
                    <th>Task</th>
                    <th>Progress</th>
                  </tr>
                </thead>
                <tbody>
                  {assignments.map((a: any) => (
                    <tr key={a.worker_id}>
                      <td className="mono">{a.worker_id}</td>
                      <td className="mono">{a.agent_type}</td>
                      <td>{a.task}</td>
                      <td className="mono">{Math.round((a.progress || 0) * 100)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel glass">
          <h2>Agent SDK task feed</h2>
          {sdkTasks.length === 0 ? (
            <p className="muted">No SDK tasks yet — run the CEO cascade to populate.</p>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>From</th>
                    <th>To</th>
                    <th>Status</th>
                    <th>Progress</th>
                  </tr>
                </thead>
                <tbody>
                  {sdkTasks.slice(0, 12).map((t: any) => (
                    <tr key={t.task_id}>
                      <td className="mono">{t.from_agent}</td>
                      <td className="mono">{t.to_agent}</td>
                      <td>{t.status}</td>
                      <td>{t.progress != null ? `${Math.round(Number(t.progress) * 100)}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="panel glass">
          <h2>Unified platform APIs</h2>
          <p className="muted">Agents call these only through VERIDIQ `/platforms` + SDK tools.</p>
          <ul className="stat-list">
            {(platforms?.platforms || []).slice(0, 14).map((p: any) => (
              <li key={p.platform}>
                <span className="mono">{p.platform}</span>
                <strong>{(p.actions || []).length} actions</strong>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel glass">
          <h2>Agent performance & health</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Runs</th>
                  <th>Success</th>
                  <th>Avg ms</th>
                </tr>
              </thead>
              <tbody>
                {Object.keys(performance).length === 0 ? (
                  <tr>
                    <td colSpan={4} className="muted">
                      No runs yet — health idle / Waiting for Tasks.
                    </td>
                  </tr>
                ) : (
                  Object.entries(performance).map(([k, v]: [string, any]) => (
                    <tr key={k}>
                      <td className="mono">{k}</td>
                      <td>{v.runs ?? 0}</td>
                      <td>{v.success_rate != null ? `${Math.round(v.success_rate * 100)}%` : "—"}</td>
                      <td className="mono">{v.avg_latency_ms ?? "—"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <section className="panel glass">
        <h2>LangGraph execution graph</h2>
        <div className="lg-map">
          {Object.entries(cc?.langgraph || {}).map(([node, agents]) => (
            <div key={node} className="lg-node glass">
              <strong>{node}</strong>
              <div className="skill-row">
                {(agents as string[]).map((a) => (
                  <span key={a} className="skill-chip mono">
                    {a}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="panel glass">
        <div className="panel-head">
          <h2>Departments</h2>
          <Link className="text-link" to="/dashboard/requests">
            Assign work →
          </Link>
        </div>
        <div className="persona-grid dense">
          {(cc?.departments?.departments || []).map((d: any) => (
            <div key={d.id} className="persona-card glass">
              <div>
                <strong>{d.name}</strong>
                <span className="muted">{d.description}</span>
                <div className="persona-meta">
                  <span className={`pill ${d.live_metrics?.waiting_for_tasks ? "" : "ok"}`}>
                    {d.live_metrics?.status_label || "Waiting for Tasks"}
                  </span>
                  <span className="mono muted">active {d.workload?.active_workers ?? 0}</span>
                  <span className="mono muted">
                    success{" "}
                    {d.workload?.success_rate != null ? `${Math.round(d.workload.success_rate * 100)}%` : "—"}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  );
}
