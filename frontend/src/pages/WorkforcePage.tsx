import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import AppShell, { AgentAvatar, EmptyState, Metric, StatusBanner } from "../components/AppShell";
import LiveAgentActivity from "../components/LiveAgentActivity";
import { api, subscribeWorkforceEvents, type WorkforceSnapshot } from "../api/client";

type LiveMode = "connecting" | "sse" | "polling";

export default function WorkforcePage() {
  const [roster, setRoster] = useState<any>(null);
  const [departments, setDepartments] = useState<any>(null);
  const [collab, setCollab] = useState<any[]>([]);
  const [dept, setDept] = useState("");
  const [q, setQ] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [liveMode, setLiveMode] = useState<LiveMode>("connecting");
  const pollRef = useRef<number | null>(null);

  const pollOnce = useCallback(async () => {
    try {
      const [r, c] = await Promise.all([api.workforceRoster(), api.collaboration()]);
      setRoster(r);
      setCollab(c.messages || []);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load workforce");
    }
  }, []);

  const refreshDepartments = useCallback(async () => {
    try {
      setDepartments(await api.departments());
    } catch {
      /* department workload stats are supplementary — ignore transient failures */
    }
  }, []);

  // Primary: subscribe to the live workforce SSE stream. Falls back to fast
  // polling automatically if the stream errors or the browser can't connect.
  useEffect(() => {
    let cancelled = false;
    const stopSse = subscribeWorkforceEvents(
      (data: WorkforceSnapshot) => {
        if (cancelled) return;
        setRoster(data.roster);
        setCollab(data.collaboration || []);
        setError(null);
        setLiveMode("sse");
        if (pollRef.current) {
          window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      },
      () => {
        if (cancelled) return;
        setLiveMode((prev) => (prev === "sse" ? "polling" : "polling"));
        void pollOnce();
        if (!pollRef.current) {
          pollRef.current = window.setInterval(() => void pollOnce(), 2000);
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

  useEffect(() => {
    void refreshDepartments();
    const id = window.setInterval(() => void refreshDepartments(), 4000);
    return () => window.clearInterval(id);
  }, [refreshDepartments]);

  const allCards: any[] = roster?.cards || [];
  const departmentOptions = roster?.departments || departments?.departments || [];

  const cards = useMemo(() => {
    return allCards.filter((c: any) => {
      if (dept && c.department?.id !== dept) return false;
      if (q) {
        const blob = `${c.name} ${c.role} ${c.agent_type} ${c.department?.name || ""}`.toLowerCase();
        if (!blob.includes(q.toLowerCase())) return false;
      }
      return true;
    });
  }, [allCards, dept, q]);

  const waiting = Boolean(roster?.workforce?.waiting_for_tasks);

  const activity = useMemo(
    () =>
      allCards
        .filter((c: any) => c.status === "working")
        .map((c: any) => ({
          agent_type: c.agent_type,
          name: c.name,
          role: c.role,
          hue: c.avatar_hue,
          task: c.current_task,
          status_label: "Running",
          stage: c.workflow_stage,
        })),
    [allCards]
  );

  const workflows = useMemo(() => {
    const active = allCards.filter((c: any) => c.status === "working" && c.job_id);
    const byJob = new Map<string, any[]>();
    for (const c of active) {
      const list = byJob.get(c.job_id) || [];
      list.push(c);
      byJob.set(c.job_id, list);
    }
    return Array.from(byJob.entries()).map(([jobId, agents]) => ({
      jobId,
      agents,
      stage: agents.find((a) => a.workflow_stage)?.workflow_stage || "running",
    }));
  }, [allCards]);

  const deptActiveCounts = useMemo(() => {
    const map = new Map<string, number>();
    for (const c of allCards) {
      if (c.status !== "working" || !c.department?.id) continue;
      map.set(c.department.id, (map.get(c.department.id) || 0) + 1);
    }
    return map;
  }, [allCards]);

  return (
    <AppShell
      title="Workforce"
      subtitle="Live organization of specialist agents — activity only when work is assigned"
      actions={
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
          <span className={`live-indicator ${liveMode === "connecting" ? "" : liveMode}`}>
            <span className="live-dot" aria-hidden />
            {liveMode === "sse" ? "Live · SSE" : liveMode === "polling" ? "Live · Polling" : "Connecting…"}
          </span>
          <button className="btn btn-ghost" type="button" onClick={() => void pollOnce()}>
            Refresh
          </button>
        </div>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} idleText="Waiting for Assignment" />

      <section className="toolbar glass">
        <input
          className="field"
          placeholder="Search agents…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="field" value={dept} onChange={(e) => setDept(e.target.value)}>
          <option value="">All departments</option>
          {departmentOptions.map((d: any) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
      </section>

      <section className="metrics">
        <Metric label="Active" value={String(roster?.workforce?.active_workers ?? 0)} />
        <Metric label="Waiting" value={String(roster?.workforce?.idle_workers ?? 0)} />
        <Metric label="Queue" value={String(roster?.workforce?.queue_depth ?? 0)} />
        <Metric label="Personas" value={String(roster?.count ?? cards.length)} />
      </section>

      <section className="panel glass">
        <div className="panel-head">
          <h2>Active workflows</h2>
        </div>
        {workflows.length === 0 ? (
          <p className="muted waiting-copy">Waiting for Assignment — no workflows currently running</p>
        ) : (
          <div className="workflow-list">
            {workflows.map((w) => (
              <div key={w.jobId} className="workflow-group">
                <div className="workflow-group-head">
                  <strong className="mono">Job {w.jobId.slice(0, 8)}</strong>
                  <span className="pill ok">{w.stage}</span>
                </div>
                <div className="workflow-agents">
                  {w.agents.map((a: any) => (
                    <Link key={a.agent_type} to={`/dashboard/agents/${a.agent_type}`} className="workflow-agent-chip">
                      <AgentAvatar name={a.name} hue={a.avatar_hue} size={22} />
                      {a.name}
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="panel glass">
        <h2>Live agent activity</h2>
        <LiveAgentActivity items={activity} />
      </section>

      <section className="panel glass">
        <div className="panel-head">
          <h2>Departments</h2>
        </div>
        <div className="dept-strip">
          {(departments?.departments || departmentOptions).map((d: any) => (
            <button
              key={d.id}
              type="button"
              className={`dept-chip ${dept === d.id ? "active" : ""}`}
              onClick={() => setDept(dept === d.id ? "" : d.id)}
            >
              <strong>{d.name}</strong>
              <span>
                {deptActiveCounts.get(d.id) ?? d.live_worker_count ?? d.workload?.active_workers ?? 0} live ·{" "}
                {d.workload?.success_rate != null ? `${Math.round(d.workload.success_rate * 100)}%` : "—"}
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="panel glass">
        <div className="panel-head">
          <h2>Collaboration feed</h2>
        </div>
        {collab.length === 0 ? (
          <p className="muted waiting-copy">No collaboration events yet — messages appear as agents work.</p>
        ) : (
          <ul className="collab-feed">
            {collab.slice(0, 12).map((m: any) => (
              <li key={m.id} className="collab-feed-item">
                <AgentAvatar name={m.speaker?.name || "A"} hue={m.speaker?.avatar_hue} size={30} />
                <div>
                  <strong>{m.speaker?.name}</strong>
                  {m.speaker?.role ? <span className="muted"> — {m.speaker.role}</span> : null}
                  <p style={{ margin: "0.25rem 0 0" }}>{m.message}</p>
                  <time>{m.timestamp}</time>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel glass">
        <h2>Workforce roster</h2>
        {cards.length === 0 ? (
          <EmptyState title="No agents match" body="Adjust search or department filters." />
        ) : (
          <div className="worker-grid">
            {cards.map((c: any) => (
              <Link key={c.agent_type} to={`/dashboard/agents/${c.agent_type}`} className="worker-card glass">
                <div className="worker-card-head">
                  <AgentAvatar name={c.name} hue={c.avatar_hue} size={48} />
                  <div>
                    <strong>{c.name}</strong>
                    <span className="muted">{c.role}</span>
                    <span className="muted">{c.department?.name || "Unassigned department"}</span>
                    <span className="muted mono">{c.email}</span>
                  </div>
                  <span className={`pill ${c.status === "working" ? "ok" : ""}`}>{c.status_label}</span>
                </div>
                <div className="worker-card-body">
                  <p>
                    {c.current_task ||
                      (c.last_status ? `Last run: ${c.last_status} — ${c.last_completed_task || ""}` : "Waiting for Assignment")}
                  </p>
                  <div className="progress-track" aria-hidden>
                    <span style={{ width: `${Math.round((c.progress || 0) * 100)}%` }} />
                  </div>
                  <ul className="worker-meta">
                    <li>
                      <span>Progress</span>
                      <strong>{c.status === "working" ? `${Math.round((c.progress || 0) * 100)}%` : "—"}</strong>
                    </li>
                    <li>
                      <span>Confidence</span>
                      <strong>
                        {c.confidence != null ? `${Math.round(Number(c.confidence) * 100)}%` : "—"}
                      </strong>
                    </li>
                    <li>
                      <span>Stage</span>
                      <strong>{c.workflow_stage || "—"}</strong>
                    </li>
                    <li>
                      <span>Started</span>
                      <strong className="mono">{c.started_at ? String(c.started_at).slice(11, 19) : "—"}</strong>
                    </li>
                    <li>
                      <span>ETA</span>
                      <strong>{c.estimated_completion_sec != null ? `${c.estimated_completion_sec}s` : "—"}</strong>
                    </li>
                    <li>
                      <span>CPU / Mem</span>
                      <strong>
                        {c.cpu_percent != null ? `${c.cpu_percent}%` : "—"} /{" "}
                        {c.memory_mb != null ? `${c.memory_mb}MB` : "—"}
                      </strong>
                    </li>
                    <li>
                      <span>Tokens</span>
                      <strong>{c.tokens_processed != null ? c.tokens_processed : "—"}</strong>
                    </li>
                    <li>
                      <span>Last task</span>
                      <strong>{c.last_completed_task || "—"}</strong>
                    </li>
                  </ul>
                </div>
              </Link>
            ))}
          </div>
        )}
        <p className="muted" style={{ marginTop: "0.85rem" }}>
          CPU/memory reflect process resources while an agent is working. Tokens are shown only when tracked — never
          fabricated.
        </p>
      </section>
    </AppShell>
  );
}
