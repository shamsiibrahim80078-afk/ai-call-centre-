import { useEffect, useState } from "react";
import { api } from "../api/client";

const STEP_LABELS: Record<string, string> = {
  agent_initialization: "Agent initialization",
  platform_connection_check: "Platform connection check",
  task_execution: "Task execution",
  result_collection: "Result collection",
  error_reporting: "Error reporting",
};

function StepIcon({ status }: { status: string }) {
  const glyph = status === "passed" ? "✓" : status === "failed" ? "✕" : status === "skipped" ? "–" : "!";
  const cls = ["passed", "failed", "skipped", "configuration_required"].includes(status) ? status : "skipped";
  return <span className={`test-step-icon ${cls}`}>{glyph}</span>;
}

/**
 * "Run Agent Test" admin capability — drives the real 5-step backend test
 * (init → platform check → task execution → result collection → error
 * reporting) and renders passed/failed steps, logs, response data, and
 * performance metrics. Never fabricates success: unconfigured platforms show
 * configuration_required honestly.
 */
export default function AgentTestRunner({ agentType }: { agentType: string }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [platform, setPlatform] = useState("");

  async function loadHistory() {
    try {
      const data = await api.agentTestHistory(agentType, 10);
      setHistory(data.runs || []);
    } catch {
      /* history is best-effort */
    }
  }

  useEffect(() => {
    void loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentType]);

  async function runTest() {
    setRunning(true);
    setError(null);
    try {
      const data = await api.agentTestRun(agentType, platform.trim() || undefined, {});
      setResult(data);
      await loadHistory();
    } catch (e: any) {
      setError(e.message || "Test run failed to execute");
    } finally {
      setRunning(false);
    }
  }

  const overall = result?.overall_status as string | undefined;

  return (
    <section className="panel glass">
      <div className="panel-head">
        <h2>Run agent test</h2>
        {overall ? (
          <span className={`pill ${overall === "passed" ? "ok" : overall === "failed" ? "bad" : ""}`}>{overall}</span>
        ) : null}
      </div>
      <p className="muted" style={{ marginTop: 0 }}>
        Executes agent initialization, platform connection check, task execution, result collection, and error
        reporting end-to-end through the live backend — the same path production runs use.
      </p>

      <div className="control-form">
        <label>
          Platform (optional)
          <input
            className="field"
            placeholder="e.g. linkedin, twilio, hubspot"
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
          />
        </label>
        <span />
        <button className="btn btn-primary btn-sm" type="button" disabled={running} onClick={() => void runTest()}>
          {running ? "Running…" : "Run test"}
        </button>
      </div>

      {error ? <div className="banner error">{error}</div> : null}

      {result ? (
        <>
          <div className="test-steps">
            {(result.steps || []).map((step: any) => (
              <div className="test-step" key={step.step}>
                <StepIcon status={step.status} />
                <div className="test-step-body">
                  <strong>{STEP_LABELS[step.step] || step.step}</strong>
                  <p>{step.message}</p>
                </div>
                <span className="test-step-duration">{step.duration_ms != null ? `${Math.round(step.duration_ms)} ms` : ""}</span>
              </div>
            ))}
          </div>

          <h3 className="subh">Performance metrics</h3>
          <ul className="stat-list">
            <li>
              <span>Total duration</span>
              {result.metrics?.total_duration_ms != null ? `${Math.round(result.metrics.total_duration_ms)} ms` : "—"}
            </li>
            <li>
              <span>Steps passed</span>
              {result.metrics?.steps_passed ?? "—"} / {result.metrics?.steps_total ?? "—"}
            </li>
            <li>
              <span>Response payload size</span>
              {result.metrics?.response_bytes != null ? `${result.metrics.response_bytes} bytes` : "—"}
            </li>
          </ul>

          <h3 className="subh">Execution logs</h3>
          <div className="test-logs">{(result.logs || []).join("\n") || "No logs captured."}</div>
        </>
      ) : (
        <p className="muted">No test run yet — click "Run test" to execute this agent's live pipeline.</p>
      )}

      <h3 className="subh">Recent test history</h3>
      {history.length === 0 ? (
        <p className="muted">No prior test runs recorded for this agent.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Platform</th>
                <th>Result</th>
                <th>Duration</th>
                <th>When</th>
              </tr>
            </thead>
            <tbody>
              {history.map((run) => (
                <tr key={run.run_uuid}>
                  <td>{run.platform || "—"}</td>
                  <td>
                    <span className={`pill ${run.overall_status === "passed" ? "ok" : run.overall_status === "failed" ? "bad" : ""}`}>
                      {run.overall_status}
                    </span>
                  </td>
                  <td className="mono">{run.duration_ms != null ? `${Math.round(run.duration_ms)} ms` : "—"}</td>
                  <td className="mono muted">{run.finished_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
