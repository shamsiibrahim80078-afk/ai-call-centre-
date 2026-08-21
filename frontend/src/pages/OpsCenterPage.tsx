import { useCallback, useEffect, useState } from "react";
import AppShell, { Metric, StatusBanner } from "../components/AppShell";
import { api } from "../api/client";

export default function OpsCenterPage() {
  const [ops, setOps] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      setOps(await api.ops());
    } catch (e: any) {
      setError(e.message || "Failed to load ops center");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 2000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const wf = ops?.workforce || {};
  const workflows = ops?.workflows || {};
  const system = ops?.system || {};
  const waiting = Boolean(wf.waiting_for_tasks);

  return (
    <AppShell
      title="Operations Center"
      subtitle="Live workers, workflows, LangGraph, RAG, and infrastructure health"
      actions={
        <button className="btn btn-ghost" type="button" onClick={() => void refresh()}>
          Refresh
        </button>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} label={ops?.status_label || wf.status_label} idleText="Waiting for Assignment" />

      <section className="metrics ops-metrics">
        <Metric label="Active AI workers" value={String(ops?.active_ai_workers ?? wf.active_workers ?? 0)} />
        <Metric label="Idle workers" value={String(ops?.idle_workers ?? wf.idle_workers ?? 0)} />
        <Metric label="Running workflows" value={String(workflows.running ?? 0)} />
        <Metric label="Completed workflows" value={String(workflows.completed ?? 0)} />
        <Metric label="Failed workflows" value={String(workflows.failed ?? 0)} />
        <Metric label="Retry / queue" value={String(ops?.retry_queue ?? wf.queue_depth ?? 0)} />
        <Metric
          label="Avg execution"
          value={ops?.average_execution_ms != null ? `${ops.average_execution_ms} ms` : "—"}
        />
        <Metric label="API latency" value={ops?.api_latency_ms != null ? `${ops.api_latency_ms} ms` : "—"} />
      </section>

      <section className="arch-strip glass">
        <strong>Infrastructure</strong>
        <span className={`pill ${system?.database === "ok" ? "ok" : ""}`}>Backend {system?.database || "…"}</span>
        <span className={`pill ok`}>SSE {ops?.sse?.status || "ready"}</span>
        <span className="muted mono">RAG {ops?.rag?.backend || system?.rag?.backend || "—"}</span>
        <span className="muted mono">vectors {ops?.rag?.points_count ?? system?.rag?.points_count ?? "—"}</span>
        <span className="muted mono">CPU {ops?.resources?.cpu_percent ?? system?.resources?.cpu_percent ?? "—"}%</span>
        <span className="muted mono">MEM {ops?.resources?.memory_mb ?? system?.resources?.memory_mb ?? "—"} MB</span>
        <span className="muted mono">pool {wf.total_workers}/{wf.max_workers}</span>
      </section>

      <section className="panel glass">
        <h2>LangGraph workflow map</h2>
        <div className="lg-map">
          {Object.entries(ops?.langgraph || {}).map(([node, agents]) => (
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
        <h2>Active assignments</h2>
        {(wf.assignments || []).length === 0 ? (
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
                  <th>Stage</th>
                  <th>Started</th>
                </tr>
              </thead>
              <tbody>
                {(wf.assignments || []).map((a: any) => (
                  <tr key={a.worker_id}>
                    <td className="mono">{a.worker_id}</td>
                    <td className="mono">{a.agent_type}</td>
                    <td>{a.task}</td>
                    <td className="mono">{Math.round((a.progress || 0) * 100)}%</td>
                    <td>{a.stage}</td>
                    <td className="mono muted">{a.started_at}</td>
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
