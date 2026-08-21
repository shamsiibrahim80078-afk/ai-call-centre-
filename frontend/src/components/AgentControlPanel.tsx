import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";

type ControlStatus = "running" | "paused" | "stopped";

function StatusPill({ status }: { status: ControlStatus }) {
  const tone = status === "running" ? "ok" : status === "stopped" ? "bad" : "";
  const label = status === "running" ? "Running" : status === "stopped" ? "Stopped" : "Paused";
  return <span className={`pill ${tone}`}>{label}</span>;
}

/**
 * Admin control section for a single agent — wired into the existing Agent
 * Workspace / Agent Detail pages (not a second workspace product). Every
 * action calls the real backend control layer: start/stop/pause/resume,
 * send a command, assign a campaign, and inspect the real command/assignment
 * history log.
 */
export default function AgentControlPanel({ agentType }: { agentType: string }) {
  const [overview, setOverview] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [command, setCommand] = useState("ping");
  const [commandResult, setCommandResult] = useState<any>(null);
  const [campaignType, setCampaignType] = useState("run_task");
  const [assignPayload, setAssignPayload] = useState("{}");
  const [assignResult, setAssignResult] = useState<any>(null);
  const [runResult, setRunResult] = useState<any>(null);

  const load = useCallback(async () => {
    try {
      const data = await api.agentControl(agentType);
      setOverview(data);
      setError(null);
    } catch (e: any) {
      setError(e.message || "Failed to load agent control state");
    }
  }, [agentType]);

  useEffect(() => {
    void load();
  }, [load]);

  async function runAction(action: "start" | "stop" | "pause" | "resume") {
    setBusy(action);
    try {
      if (action === "start") await api.agentControlStart(agentType);
      if (action === "stop") await api.agentControlStop(agentType);
      if (action === "pause") await api.agentControlPause(agentType);
      if (action === "resume") await api.agentControlResume(agentType);
      await load();
    } catch (e: any) {
      setError(e.message || `Failed to ${action} agent`);
    } finally {
      setBusy(null);
    }
  }

  async function runNow() {
    setBusy("run");
    setRunResult(null);
    try {
      const result = await api.runAgent(agentType, {});
      setRunResult(result);
      await load();
    } catch (e: any) {
      setRunResult({ ok: false, status: "error", error: e.message });
    } finally {
      setBusy(null);
    }
  }

  async function sendCommand() {
    setBusy("command");
    try {
      const result = await api.agentControlCommand(agentType, command, {});
      setCommandResult(result);
      await load();
    } catch (e: any) {
      setCommandResult({ ok: false, status: "error", error: e.message });
    } finally {
      setBusy(null);
    }
  }

  async function assignCampaign() {
    setBusy("assign");
    try {
      let payload: Record<string, unknown> = {};
      try {
        payload = assignPayload.trim() ? JSON.parse(assignPayload) : {};
      } catch {
        setAssignResult({ ok: false, status: "error", error: "Payload must be valid JSON" });
        setBusy(null);
        return;
      }
      const result = await api.agentControlAssign(agentType, campaignType, payload);
      setAssignResult(result);
      await load();
    } catch (e: any) {
      setAssignResult({ ok: false, status: "error", error: e.message });
    } finally {
      setBusy(null);
    }
  }

  const status: ControlStatus = overview?.control?.status || "running";

  return (
    <section className="panel glass control-panel">
      <div className="panel-head">
        <h2>Agent control</h2>
        <StatusPill status={status} />
      </div>
      {error ? <div className="banner error">{error}</div> : null}

      <div className="control-actions">
        <button className="btn btn-primary btn-sm" type="button" disabled={busy !== null || status === "running"} onClick={() => runAction("start")}>
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
        <button className="btn btn-ghost btn-sm" type="button" disabled={busy !== null || status === "paused"} onClick={() => runAction("pause")}>
          Pause
        </button>
        <button className="btn btn-ghost btn-sm" type="button" disabled={busy !== null || status === "running"} onClick={() => runAction("resume")}>
          Resume
        </button>
        <button className="btn btn-danger btn-sm" type="button" disabled={busy !== null || status === "stopped"} onClick={() => runAction("stop")}>
          Stop
        </button>
      </div>
      {runResult ? (
        <div className="control-result mono">
          <span className={`pill ${runResult.status === "started" || runResult.ok ? "ok" : "bad"}`} style={{ marginRight: "0.5rem" }}>
            {runResult.status || (runResult.ok ? "ok" : "failed")}
          </span>
          {runResult.error || runResult.detail || "Run started — see Live activity log / current workload above."}
        </div>
      ) : null}

      <h3 className="subh">Send command</h3>
      <div className="control-form">
        <label>
          Command
          <select className="field" value={command} onChange={(e) => setCommand(e.target.value)}>
            <option value="ping">ping</option>
            <option value="run_task">run_task</option>
          </select>
        </label>
        <span className="muted" style={{ fontSize: "0.78rem" }}>
          {command === "run_task" ? "Executes a real task through this agent's live pipeline." : "Health-check round trip only."}
        </span>
        <button className="btn btn-ghost btn-sm" type="button" disabled={busy !== null} onClick={() => void sendCommand()}>
          {busy === "command" ? "Sending…" : "Send"}
        </button>
      </div>
      {commandResult ? (
        <div className="control-result mono">
          <span className={`pill ${commandResult.ok ? "ok" : "bad"}`} style={{ marginRight: "0.5rem" }}>
            {commandResult.status}
          </span>
          {commandResult.error || "Command executed."}
        </div>
      ) : null}

      <h3 className="subh">Assign campaign / task</h3>
      <div className="control-form">
        <label>
          Campaign type
          <select className="field" value={campaignType} onChange={(e) => setCampaignType(e.target.value)}>
            <option value="run_task">run_task</option>
            <option value="verify">verify</option>
            <option value="market_intelligence">market_intelligence</option>
            <option value="comms">comms</option>
            <option value="ai_calling">ai_calling</option>
          </select>
        </label>
        <label>
          Payload (JSON)
          <input className="field mono" value={assignPayload} onChange={(e) => setAssignPayload(e.target.value)} placeholder="{}" />
        </label>
        <button className="btn btn-ghost btn-sm" type="button" disabled={busy !== null} onClick={() => void assignCampaign()}>
          {busy === "assign" ? "Assigning…" : "Assign"}
        </button>
      </div>
      {assignResult ? (
        <div className="control-result mono">
          <span className={`pill ${assignResult.ok ? "ok" : "bad"}`} style={{ marginRight: "0.5rem" }}>
            {assignResult.status || (assignResult.ok ? "ok" : "failed")}
          </span>
          {assignResult.error || assignResult.assignment?.status || "Assignment submitted."}
        </div>
      ) : null}

      <h3 className="subh">Command history</h3>
      {(overview?.commands || []).length === 0 ? (
        <p className="muted">No admin commands issued yet for this agent.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Command</th>
                <th>Status</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {(overview?.commands || []).slice(0, 8).map((c: any) => (
                <tr key={c.command_uuid}>
                  <td>{c.command}</td>
                  <td>
                    <span className={`pill ${c.status.startsWith("completed") ? "ok" : c.status.startsWith("rejected") || c.status === "failed" ? "bad" : ""}`}>
                      {c.status}
                    </span>
                  </td>
                  <td className="mono muted">{c.finished_at || c.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="subh">Assignment history</h3>
      {(overview?.assignments || []).length === 0 ? (
        <p className="muted">No campaigns/tasks assigned yet for this agent.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Campaign</th>
                <th>Status</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {(overview?.assignments || []).slice(0, 8).map((a: any) => (
                <tr key={a.assignment_uuid}>
                  <td>{a.campaign_type}</td>
                  <td>
                    <span className={`pill ${["completed", "queued", "queued_for_approval", "draft_ready"].includes(a.status) ? "ok" : a.status === "failed" ? "bad" : ""}`}>
                      {a.status}
                    </span>
                  </td>
                  <td className="mono muted">{a.finished_at || a.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
