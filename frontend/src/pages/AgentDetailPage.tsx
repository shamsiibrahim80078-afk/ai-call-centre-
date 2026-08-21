import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import AppShell, { AgentAvatar, Metric, StatusBanner } from "../components/AppShell";
import AgentControlPanel from "../components/AgentControlPanel";
import AgentTestRunner from "../components/AgentTestRunner";
import { api, subscribeWorkforceEvents, type WorkforceSnapshot } from "../api/client";

type AgentView = {
  agent_type: string;
  name: string;
  role: string;
  avatar_hue: number;
  email?: string;
  department?: any;
  biography?: string;
  skills: string[];
  status: string;
  status_label: string;
  last_status?: string | null;
  current_task?: string | null;
  progress?: number | null;
  confidence?: number | null;
  workflow_stage?: string | null;
  job_id?: string | null;
  started_at?: string | null;
  connected_tools: string[];
  assigned_models: string[];
  langgraph_nodes: string[];
  activity_history: any[];
  metrics: { runs?: number; success_rate?: number; avg_latency_ms?: number; reliability_score?: number };
};

function fromRosterCard(card: any): AgentView {
  return {
    agent_type: card.agent_type,
    name: card.name,
    role: card.role,
    avatar_hue: card.avatar_hue,
    email: card.email,
    department: card.department,
    biography: card.biography,
    skills: card.skills || [],
    status: card.status,
    status_label: card.status_label,
    last_status: card.last_status,
    current_task: card.current_task,
    progress: card.progress,
    confidence: card.confidence,
    workflow_stage: card.workflow_stage,
    job_id: card.job_id,
    started_at: card.started_at,
    connected_tools: card.connected_tools || [],
    assigned_models: card.assigned_models || [],
    langgraph_nodes: card.langgraph_nodes || [],
    activity_history: card.activity_history || [],
    metrics: card.metrics || {},
  };
}

function fromDetail(detail: any): AgentView {
  const identity = detail.identity || {};
  const assignment = detail.current_assignment || {};
  return {
    agent_type: detail.agent_type,
    name: identity.name || detail.name,
    role: identity.role,
    avatar_hue: identity.avatar_hue,
    email: detail.email || identity.internal_email,
    department: detail.department,
    biography: detail.biography || identity.persona_note,
    skills: detail.skills || identity.skills || [],
    status: detail.status,
    status_label: detail.status_label,
    last_status: detail.last_status,
    current_task: assignment.task,
    progress: assignment.progress,
    confidence: assignment.confidence,
    workflow_stage: detail.workflow_stage || assignment.stage,
    job_id: detail.current_workflow || assignment.job_id,
    started_at: assignment.started_at,
    connected_tools: detail.connected_tools || [],
    assigned_models: detail.assigned_models || [],
    langgraph_nodes: detail.langgraph_nodes || [],
    activity_history: detail.activity_history || detail.task_history || detail.execution_history || [],
    metrics: detail.metrics || {},
  };
}

export default function AgentDetailPage() {
  const { agentType = "" } = useParams();
  const [view, setView] = useState<AgentView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [liveMode, setLiveMode] = useState<"connecting" | "sse" | "polling">("connecting");
  const pollRef = useRef<number | null>(null);

  const pollOnce = useCallback(async () => {
    if (!agentType) return;
    try {
      const detail = await api.agent(agentType);
      setView(fromDetail(detail));
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load agent");
    }
  }, [agentType]);

  useEffect(() => {
    if (!agentType) return undefined;
    let cancelled = false;
    // Prime with a full detail fetch immediately (SSE snapshot arrives ~0-2s later).
    void pollOnce();
    const stopSse = subscribeWorkforceEvents(
      (data: WorkforceSnapshot) => {
        if (cancelled) return;
        const card = (data.cards || []).find((c: any) => c.agent_type === agentType);
        if (!card) return;
        setView(fromRosterCard(card));
        setError(null);
        setLiveMode("sse");
        if (pollRef.current) {
          window.clearInterval(pollRef.current);
          pollRef.current = null;
        }
      },
      () => {
        if (cancelled) return;
        setLiveMode("polling");
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
  }, [agentType, pollOnce]);

  const m = view?.metrics || {};
  const waiting = view ? view.status !== "working" : true;

  return (
    <AppShell
      title={view?.name ? view.name : "Agent profile"}
      subtitle={`${view?.role || ""} · ${view?.department?.name || "AI Organization"}`}
      actions={
        <div style={{ display: "flex", gap: "0.6rem", alignItems: "center" }}>
          <span className={`live-indicator ${liveMode === "connecting" ? "" : liveMode}`}>
            <span className="live-dot" aria-hidden />
            {liveMode === "sse" ? "Live · SSE" : liveMode === "polling" ? "Live · Polling" : "Connecting…"}
          </span>
          <Link className="btn btn-ghost" to="/dashboard/runtime">
            Open Live Runtime
          </Link>
          <Link className="btn btn-ghost" to="/dashboard/workforce">
            Back to workforce
          </Link>
        </div>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} idleText="Waiting for Assignment" />

      <section className="agent-hero glass">
        <AgentAvatar name={view?.name || "A"} hue={view?.avatar_hue} size={72} />
        <div>
          <p className="muted">{view?.biography}</p>
          <p className="muted mono" style={{ marginTop: "0.35rem" }}>
            {view?.email}
          </p>
          <div className="skill-row" style={{ marginTop: "0.65rem" }}>
            {(view?.skills || []).map((s: string) => (
              <span key={s} className="skill-chip">
                {s}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="metrics">
        <Metric label="Status" value={view?.status_label || (waiting ? "Waiting for Assignment" : "Working")} />
        <Metric label="Runs" value={String(m.runs ?? 0)} />
        <Metric
          label="Reliability"
          value={m.reliability_score != null ? `${Math.round(m.reliability_score * 100)}%` : "—"}
        />
        <Metric label="Avg exec" value={m.avg_latency_ms != null ? `${m.avg_latency_ms} ms` : "—"} />
      </section>

      <div className="two-col">
        <section className="panel glass">
          <h2>Current workload</h2>
          {waiting ? (
            <p className="muted waiting-copy">
              {view?.last_status
                ? `Waiting for Assignment — last run ${view.last_status}`
                : "Waiting for Assignment"}
            </p>
          ) : (
            <ul className="stat-list">
              <li>
                <span>Task</span>
                <strong>{view?.current_task}</strong>
              </li>
              <li>
                <span>Workflow stage</span>
                <strong>{view?.workflow_stage || "—"}</strong>
              </li>
              <li>
                <span>Progress</span>
                <strong>{Math.round((view?.progress || 0) * 100)}%</strong>
              </li>
              <li>
                <span>Confidence</span>
                <strong>{view?.confidence != null ? `${Math.round(Number(view.confidence) * 100)}%` : "—"}</strong>
              </li>
              <li>
                <span>Started</span>
                <strong className="mono">{view?.started_at}</strong>
              </li>
              <li>
                <span>Job</span>
                <strong className="mono">{view?.job_id || "—"}</strong>
              </li>
            </ul>
          )}
          <h3 className="subh">Assigned models</h3>
          <ul className="plain-list">
            {(view?.assigned_models || []).map((s: string) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <h3 className="subh">Connected tools</h3>
          <ul className="plain-list">
            {(view?.connected_tools || []).map((s: string) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          <h3 className="subh">LangGraph state / workflow nodes</h3>
          <div className="skill-row">
            {(view?.langgraph_nodes || []).length === 0 ? (
              <span className="muted">Not currently wired to a LangGraph node.</span>
            ) : (
              (view?.langgraph_nodes || []).map((n: string) => (
                <span key={n} className="skill-chip">
                  {n}
                </span>
              ))
            )}
          </div>
        </section>

        <section className="panel glass">
          <h2>Live activity log</h2>
          {(view?.activity_history || []).length === 0 ? (
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
                  {(view?.activity_history || []).map((h: any, i: number) => (
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

      <div className="two-col">
        {agentType ? <AgentControlPanel agentType={agentType} /> : null}
        {agentType ? <AgentTestRunner agentType={agentType} /> : null}
      </div>
    </AppShell>
  );
}
