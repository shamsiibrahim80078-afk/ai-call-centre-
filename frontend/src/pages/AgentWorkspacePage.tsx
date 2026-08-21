import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import AppShell, { AgentAvatar, EmptyState, Metric, StatusBanner } from "../components/AppShell";
import { api, subscribeWorkforceEvents, type WorkforceSnapshot } from "../api/client";

type LiveMode = "connecting" | "sse" | "polling";

function pct(n: number | null | undefined): string {
  return n != null ? `${Math.round(Number(n) * 100)}%` : "—";
}

/** Start/Run/Stop (+ Pause/Resume) inline in the workspace hero — the full
 * control history + "Run Agent Test" panel lives on the agent's full profile
 * page (AgentDetailPage) to avoid duplicating a second workspace. "Run" hits
 * the real backend immediately (non-blocking) and the agent shows up as
 * "Live" in the rail / SSE overlay for the duration of the run. */
function QuickControls({ agentType, controlStatus, onChanged }: { agentType: string; controlStatus?: string; onChanged: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [runNote, setRunNote] = useState<string | null>(null);
  const status = controlStatus || "running";

  async function run(action: "start" | "stop" | "pause" | "resume") {
    setBusy(action);
    try {
      if (action === "start") await api.agentControlStart(agentType);
      if (action === "stop") await api.agentControlStop(agentType);
      if (action === "pause") await api.agentControlPause(agentType);
      if (action === "resume") await api.agentControlResume(agentType);
      onChanged();
    } finally {
      setBusy(null);
    }
  }

  async function runNow() {
    setBusy("run");
    setRunNote(null);
    try {
      const result = await api.runAgent(agentType, {});
      if (result.status === "started") {
        setRunNote("Running now — watch this agent go Live below.");
      } else if (result.detail) {
        setRunNote(String(result.detail));
      }
      onChanged();
    } catch (e: any) {
      setRunNote(e.message || "Run failed to start");
    } finally {
      setBusy(null);
      window.setTimeout(() => setRunNote(null), 6000);
    }
  }

  return (
    <div style={{ marginTop: "0.5rem" }}>
      <div className="control-actions">
        <button className="btn btn-primary btn-sm" type="button" disabled={busy !== null || status === "running"} onClick={() => void run("start")}>
          Start
        </button>
        <button
          className="btn btn-primary btn-sm"
          type="button"
          disabled={busy !== null || status !== "running"}
          onClick={() => void runNow()}
          title="Execute this agent right now through the live backend"
        >
          {busy === "run" ? "Running…" : "Run now"}
        </button>
        <button className="btn btn-ghost btn-sm" type="button" disabled={busy !== null || status === "paused"} onClick={() => void run("pause")}>
          Pause
        </button>
        <button className="btn btn-ghost btn-sm" type="button" disabled={busy !== null || status === "running"} onClick={() => void run("resume")}>
          Resume
        </button>
        <button className="btn btn-danger btn-sm" type="button" disabled={busy !== null || status === "stopped"} onClick={() => void run("stop")}>
          Stop
        </button>
      </div>
      {runNote ? (
        <p className="muted" style={{ marginTop: "0.4rem", fontSize: "0.82rem" }}>
          {runNote}
        </p>
      ) : null}
    </div>
  );
}

export default function AgentWorkspacePage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("agent") || "";

  const [workspace, setWorkspace] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveMode, setLiveMode] = useState<LiveMode>("connecting");
  const [deptFilter, setDeptFilter] = useState("");
  const [q, setQ] = useState("");
  const pollRef = useRef<number | null>(null);

  const pollOnce = useCallback(async () => {
    try {
      const data = await api.workspace();
      setWorkspace(data);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load agent workspace");
    }
  }, []);

  // Full workspace refresh (task queue, live logs, platform activity, connected APIs)
  useEffect(() => {
    void pollOnce();
    const id = window.setInterval(() => void pollOnce(), 4000);
    return () => window.clearInterval(id);
  }, [pollOnce]);

  // Live overlay: merge fast SSE status/progress updates into the polled workspace.
  useEffect(() => {
    let cancelled = false;
    const stopSse = subscribeWorkforceEvents(
      (data: WorkforceSnapshot) => {
        if (cancelled) return;
        setLiveMode("sse");
        setWorkspace((prev: any) => {
          if (!prev) return prev;
          const byType = new Map((data.cards || []).map((c: any) => [c.agent_type, c]));
          const agents = (prev.agents || []).map((a: any) => {
            const live = byType.get(a.agent_type);
            return live
              ? {
                  ...a,
                  status: live.status,
                  status_label: live.status_label,
                  current_task: live.current_task,
                  progress: live.progress,
                  confidence: live.confidence,
                  workflow_stage: live.workflow_stage,
                  job_id: live.job_id,
                  started_at: live.started_at,
                  last_status: live.last_status,
                  last_completed_task: live.last_completed_task,
                }
              : a;
          });
          return { ...prev, agents, workforce: data.roster?.workforce || prev.workforce };
        });
        if (pollRef.current) {
          window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      },
      () => {
        if (cancelled) return;
        setLiveMode("polling");
        if (!pollRef.current) {
          pollRef.current = window.setInterval(() => void pollOnce(), 3000);
        }
      }
    );
    return () => {
      cancelled = true;
      stopSse();
      if (pollRef.current) {
        window.clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [pollOnce]);

  const allAgents: any[] = workspace?.agents || [];
  const departments: any[] = workspace?.departments || [];

  const visibleAgents = useMemo(() => {
    return allAgents.filter((a) => {
      if (deptFilter && a.department?.id !== deptFilter) return false;
      if (q) {
        const blob = `${a.name} ${a.role} ${a.agent_type}`.toLowerCase();
        if (!blob.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [allAgents, deptFilter, q]);

  const agent = useMemo(
    () => allAgents.find((a) => a.agent_type === selected) || null,
    [allAgents, selected]
  );

  useEffect(() => {
    if (!selected && visibleAgents.length > 0) {
      setParams({ agent: visibleAgents[0].agent_type }, { replace: true });
    }
  }, [selected, visibleAgents, setParams]);

  function selectAgent(agentType: string) {
    setParams({ agent: agentType });
  }

  const waiting = Boolean(workspace?.waiting_for_tasks);
  const m = agent?.metrics || {};

  return (
    <AppShell
      title="Agent Workspace"
      subtitle="Enterprise organization view — every agent's live queue, logs, and connected APIs"
      actions={
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
          <span className={`live-indicator ${liveMode === "connecting" ? "" : liveMode}`}>
            <span className="live-dot" aria-hidden />
            {liveMode === "sse" ? "Live · SSE" : liveMode === "polling" ? "Live · Polling" : "Connecting…"}
          </span>
          <Link className="btn btn-ghost" to="/dashboard/workforce">
            Workforce view
          </Link>
        </div>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} idleText="Waiting for Assignment" />

      <section className="metrics">
        <Metric label="Active" value={String(workspace?.workforce?.active_workers ?? 0)} />
        <Metric label="Waiting" value={String(workspace?.workforce?.idle_workers ?? 0)} />
        <Metric label="Departments" value={String(departments.length)} />
        <Metric label="Personas" value={String(workspace?.count ?? allAgents.length)} />
      </section>

      <section className="arch-strip glass" style={{ marginBottom: "1rem" }}>
        <strong>OS / SDK</strong>
        <Link className="text-link" to="/dashboard/command-center">
          Command Center →
        </Link>
        <span className="muted mono">Live pool + SDK tasks + platform probe live there</span>
        <Link className="text-link" to="/dashboard/integrations">
          Integrations →
        </Link>
      </section>

      <div className="workspace-layout">
        <aside className="workspace-rail glass">
          <div className="workspace-rail-search">
            <input
              className="field"
              placeholder="Search agents…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>
          <div className="workspace-rail-depts">
            <button
              type="button"
              className={`dept-chip ${deptFilter === "" ? "active" : ""}`}
              onClick={() => setDeptFilter("")}
            >
              <strong>All departments</strong>
              <span>{allAgents.length} agents</span>
            </button>
            {departments.map((d: any) => (
              <button
                key={d.id}
                type="button"
                className={`dept-chip ${deptFilter === d.id ? "active" : ""}`}
                onClick={() => setDeptFilter(deptFilter === d.id ? "" : d.id)}
              >
                <strong>{d.name}</strong>
                <span>
                  {d.active_count} live · {d.idle_count} waiting
                </span>
              </button>
            ))}
          </div>
          <ul className="workspace-agent-list">
            {visibleAgents.length === 0 ? (
              <li className="muted workspace-agent-empty">No agents match.</li>
            ) : (
              visibleAgents.map((a: any) => (
                <li key={a.agent_type}>
                  <button
                    type="button"
                    className={`workspace-agent-row ${a.agent_type === selected ? "active" : ""}`}
                    onClick={() => selectAgent(a.agent_type)}
                  >
                    <AgentAvatar name={a.name} hue={a.avatar_hue} size={32} />
                    <div className="workspace-agent-row-text">
                      <strong>{a.name}</strong>
                      <span className="muted">{a.department?.name || "Unassigned"}</span>
                    </div>
                    <span className={`pill ${a.status === "working" ? "ok" : ""}`}>
                      {a.status === "working" ? "Live" : "Idle"}
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
        </aside>

        <section className="workspace-main">
          {!agent ? (
            <div className="panel glass">
              <EmptyState title="Select an agent" body="Choose an agent from the rail to open their workspace." />
            </div>
          ) : (
            <>
              <section className="agent-hero glass">
                <AgentAvatar name={agent.name} hue={agent.avatar_hue} size={72} />
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", flexWrap: "wrap" }}>
                    <strong style={{ fontSize: "1.1rem" }}>{agent.name}</strong>
                    <span className={`pill ${agent.status === "working" ? "ok" : ""}`}>{agent.status_label}</span>
                    {agent.control_status && agent.control_status !== "running" ? (
                      <span className="pill bad">{agent.control_status_label}</span>
                    ) : null}
                  </div>
                  <p className="muted">
                    {agent.role} · {agent.department?.name || "Unassigned department"}
                  </p>
                  <p className="muted">{agent.biography}</p>
                  <p className="muted mono" style={{ marginTop: "0.35rem" }}>
                    {agent.email}
                  </p>
                  <div className="skill-row" style={{ marginTop: "0.65rem" }}>
                    {(agent.skills || []).map((s: string) => (
                      <span key={s} className="skill-chip">
                        {s}
                      </span>
                    ))}
                  </div>
                  <QuickControls agentType={agent.agent_type} controlStatus={agent.control_status} onChanged={() => void pollOnce()} />
                </div>
                <Link className="btn btn-ghost" to={`/dashboard/agents/${agent.agent_type}`}>
                  Full profile &amp; test runner
                </Link>
              </section>

              <section className="metrics">
                <Metric label="Status" value={agent.status_label} />
                <Metric label="Runs" value={String(m.runs ?? 0)} />
                <Metric label="Reliability" value={pct(m.success_rate)} />
                <Metric label="Avg exec" value={m.avg_latency_ms != null ? `${m.avg_latency_ms} ms` : "—"} />
              </section>

              <div className="two-col">
                <section className="panel glass">
                  <h2>Current task</h2>
                  {agent.status !== "working" ? (
                    <p className="muted waiting-copy">
                      {agent.last_status
                        ? `Waiting for Assignment — last run ${agent.last_status}`
                        : "Waiting for Assignment"}
                    </p>
                  ) : (
                    <ul className="stat-list">
                      <li>
                        <span>Task</span>
                        <strong>{agent.current_task}</strong>
                      </li>
                      <li>
                        <span>Workflow stage</span>
                        <strong>{agent.workflow_stage || "—"}</strong>
                      </li>
                      <li>
                        <span>Progress</span>
                        <strong>{pct(agent.progress)}</strong>
                      </li>
                      <li>
                        <span>Confidence</span>
                        <strong>{pct(agent.confidence)}</strong>
                      </li>
                      <li>
                        <span>Job</span>
                        <strong className="mono">{agent.job_id || "—"}</strong>
                      </li>
                    </ul>
                  )}

                  <h3 className="subh">Task queue</h3>
                  {(agent.task_queue || []).length === 0 ? (
                    <p className="muted">Waiting for Assignment — queue is empty.</p>
                  ) : (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Task</th>
                            <th>Stage</th>
                            <th>Progress</th>
                            <th>Job</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(agent.task_queue || []).map((t: any, i: number) => (
                            <tr key={`${t.worker_id}-${i}`}>
                              <td>{t.task}</td>
                              <td>{t.stage}</td>
                              <td className="mono">{pct(t.progress)}</td>
                              <td className="mono muted">{(t.job_id || "").slice(0, 8)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <h3 className="subh">Workflow state / LangGraph nodes</h3>
                  <div className="skill-row">
                    {(agent.workflow_state?.nodes || []).length === 0 ? (
                      <span className="muted">Not currently wired to a LangGraph node.</span>
                    ) : (
                      (agent.workflow_state?.nodes || []).map((n: string) => (
                        <span key={n} className="skill-chip">
                          {n}
                        </span>
                      ))
                    )}
                  </div>

                  <h3 className="subh">Connected tools / APIs</h3>
                  <ul className="plain-list">
                    {[...(agent.connected_tools || []), ...(agent.assigned_models || [])].map((s: string) => (
                      <li key={s}>{s}</li>
                    ))}
                    {(agent.connected_apis || []).map((api2: any, i: number) => (
                      <li key={`${api2.name}-${i}`}>
                        {api2.name}{" "}
                        <span className={`pill ${api2.status === "ok" ? "ok" : ""}`} style={{ marginLeft: "0.4rem" }}>
                          {api2.status}
                        </span>
                      </li>
                    ))}
                  </ul>
                </section>

                <section className="panel glass">
                  <h2>Live logs</h2>
                  {(agent.live_logs || []).length === 0 ? (
                    <p className="muted waiting-copy">No collaboration events for this agent yet.</p>
                  ) : (
                    <ul className="collab-feed">
                      {(agent.live_logs || []).map((m2: any) => (
                        <li key={m2.id} className="collab-feed-item">
                          <AgentAvatar name={m2.speaker?.name || "A"} hue={m2.speaker?.avatar_hue} size={26} />
                          <div>
                            <p style={{ margin: 0 }}>{m2.message}</p>
                            <time>{m2.timestamp}</time>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}

                  <h3 className="subh">Platform activity</h3>
                  {(agent.platform_activity || []).length === 0 ? (
                    <p className="muted">No platform/integration calls recorded for this agent yet.</p>
                  ) : (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Platform</th>
                            <th>Task</th>
                            <th>Status</th>
                            <th>When</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(agent.platform_activity || []).map((p: any) => (
                            <tr key={p.id}>
                              <td>{p.platform}</td>
                              <td>{p.recent_activity || p.task}</td>
                              <td>
                                <span className={`pill ${p.completion_status === "completed" ? "ok" : p.completion_status === "failed" ? "bad" : ""}`}>
                                  {p.completion_status}
                                </span>
                              </td>
                              <td className="mono muted">{p.finished_at}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}

                  <h3 className="subh">Execution history</h3>
                  {(agent.activity_history || []).length === 0 ? (
                    <p className="muted">No runs yet.</p>
                  ) : (
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Task</th>
                            <th>OK</th>
                            <th>Latency</th>
                            <th>Finished</th>
                          </tr>
                        </thead>
                        <tbody>
                          {(agent.activity_history || []).map((h: any, i: number) => (
                            <tr key={`${h.finished_at}-${i}`}>
                              <td>{h.task}</td>
                              <td>
                                <span className={`pill ${h.ok ? "ok" : "bad"}`}>{h.ok ? "ok" : "fail"}</span>
                              </td>
                              <td className="mono">{h.latency_ms != null ? `${Math.round(h.latency_ms)} ms` : "—"}</td>
                              <td className="mono muted">{h.finished_at}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </section>
              </div>
            </>
          )}
        </section>
      </div>
    </AppShell>
  );
}
