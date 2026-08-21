import { type FormEvent, useCallback, useEffect, useState } from "react";
import AppShell, { Metric, StatusBanner } from "../components/AppShell";
import { ResultCard } from "../components/ResultCard";
import { api, subscribeJobEvents, type JobEvent } from "../api/client";

export default function VerifyPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [workforce, setWorkforce] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [statement, setStatement] = useState(
    "The company announced a 40% revenue increase in Q2 and confirmed the acquisition closed last Friday."
  );
  const [result, setResult] = useState<any>(null);
  const [liveEvents, setLiveEvents] = useState<JobEvent[]>([]);
  const [sseStatus, setSseStatus] = useState<"idle" | "connecting" | "live" | "closed" | "error">("idle");
  const [liveConfidence, setLiveConfidence] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [m, w] = await Promise.all([api.verifyMetrics(), api.workforce()]);
      setMetrics(m);
      setWorkforce(w);
    } catch (e: any) {
      setError(e.message || "Failed to load verify metrics");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(id);
  }, [refresh]);

  async function runLiveVerify(text: string) {
    setBusy(true);
    setError(null);
    setLiveEvents([]);
    setResult(null);
    setLiveConfidence(null);
    setSseStatus("connecting");
    try {
      const queued = await api.verify(text.trim(), "VERIDIQ Verification", true);
      const jobUuid = queued.job_uuid as string;
      setSseStatus("live");
      await new Promise<void>((resolve, reject) => {
        const stop = subscribeJobEvents(
          jobUuid,
          (ev) => {
            setLiveEvents((prev) => [...prev.slice(-50), ev]);
            if (typeof ev.truth_score === "number") setLiveConfidence(ev.truth_score);
            if (ev.stage === "failed") setSseStatus("error");
          },
          () => {
            stop();
            setSseStatus("closed");
            resolve();
          }
        );
        window.setTimeout(() => {
          stop();
          setSseStatus("error");
          reject(new Error("Verification timed out waiting for SSE completion"));
        }, 180000);
      });
      const job = await api.job(jobUuid);
      const out = job.result || job;
      setResult({ ...out, job_id: jobUuid });
      if (typeof out.truth_score === "number") setLiveConfidence(out.truth_score);
      await refresh();
    } catch (err: any) {
      setSseStatus("error");
      setError(err.message || "Verification failed");
    } finally {
      setBusy(false);
    }
  }

  async function onVerify(e: FormEvent) {
    e.preventDefault();
    await runLiveVerify(statement);
  }

  async function onUpload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const fd = new FormData(formEl);
    if (!fd.get("text") && !(fd.get("video") as File)?.size && !(fd.get("audio") as File)?.size && !(fd.get("image") as File)?.size) {
      setError("Provide text or a media file");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const out = await api.uploadVerify(fd);
      setResult(out);
      await refresh();
    } catch (err: any) {
      setError(err.message || "Upload verification failed");
    } finally {
      setBusy(false);
    }
  }

  async function attestCurrent() {
    if (!result?.job_id) return;
    try {
      const out = await api.attest(result.job_id);
      window.alert(`Attestation ${out.mode}: hash ${(out.report_hash || "").slice(0, 18)}…`);
    } catch (err: any) {
      setError(err.message || "Attestation failed");
    }
  }

  const waiting = Boolean(metrics?.waiting_for_tasks) && sseStatus !== "live";
  const assignments = (workforce?.assignments || []).filter((a: any) =>
    ["statement_verification", "fact_checking", "evidence_collection", "lie_detection"].includes(a.agent_type)
  );

  return (
    <AppShell
      title="Verification Center"
      subtitle="Live claim analysis with LangGraph orchestration"
      actions={
        <span className={`pill ${sseStatus === "live" ? "ok" : sseStatus === "error" ? "bad" : ""}`}>SSE {sseStatus}</span>
      }
    >
      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} />

      <section className="metrics">
        <Metric label="Running" value={String(metrics?.running_verifications ?? 0)} />
        <Metric label="Completed" value={String(metrics?.completed_verifications ?? 0)} />
        <Metric
          label="Avg confidence"
          value={
            typeof metrics?.average_confidence === "number"
              ? `${Math.round(metrics.average_confidence * 100)}%`
              : liveConfidence != null
                ? `${Math.round(liveConfidence * 100)}%`
                : "—"
          }
        />
        <Metric label="Evidence collected" value={String(metrics?.evidence_collected ?? 0)} />
      </section>

      <section className="panel glass workflow-panel">
        <h2>LangGraph execution</h2>
        <div className="workflow-nodes">
          {["route", "perception", "evidence_rag", "verification", "reasoning", "finalize"].map((node) => {
            const hit = liveEvents.some(
              (e) =>
                e.stage === node ||
                e.stage?.includes(node) ||
                (node === "finalize" && e.stage === "completed") ||
                (node === "evidence_rag" && (e.stage === "rag" || e.stage === "rag_hits"))
            );
            return (
              <div key={node} className={`wf-node ${hit ? "is-on" : ""}`}>
                {node}
              </div>
            );
          })}
        </div>
        {assignments.length === 0 ? (
          <p className="muted" style={{ marginTop: "0.75rem" }}>
            Waiting for Tasks
          </p>
        ) : (
          <ul className="assignment-list" style={{ marginTop: "0.85rem" }}>
            {assignments.map((a: any) => (
              <li key={a.worker_id}>
                <span className="mono">{a.agent_type}</span>
                <span>{a.task}</span>
                <span className="mono">{Math.round((a.progress || 0) * 100)}%</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="panel glass">
        <h2>Live verification</h2>
        <p className="muted">Paste a statement or upload media. Progress streams over SSE from the backend.</p>
        <form onSubmit={onVerify} className="verify-form">
          <textarea className="field" rows={5} value={statement} onChange={(e) => setStatement(e.target.value)} required />
          <button className="btn btn-primary" type="submit" disabled={busy || !statement.trim()}>
            {busy ? "Agents collaborating…" : "Uncover the truth"}
          </button>
        </form>
        <form className="upload-form" onSubmit={onUpload}>
          <input className="field" name="text" placeholder="Optional transcript / caption" />
          <div className="upload-row">
            <label>
              Video
              <input type="file" name="video" accept="video/*" />
            </label>
            <label>
              Audio
              <input type="file" name="audio" accept="audio/*" />
            </label>
            <label>
              Image
              <input type="file" name="image" accept="image/*" />
            </label>
          </div>
          <button className="btn btn-ghost" type="submit" disabled={busy}>
            Run media pipeline
          </button>
        </form>
        {liveEvents.length > 0 ? (
          <div className="sse-log" aria-live="polite">
            <h3>Agent activity timeline</h3>
            <ul>
              {liveEvents.slice(-14).map((ev, i) => (
                <li key={`${ev.stage}-${i}`}>
                  <span className="mono">{ev.stage}</span>
                  <span>{ev.message || ev.agent_type || ""}</span>
                  {typeof ev.truth_score === "number" ? (
                    <span className="mono">{Math.round(ev.truth_score * 100)}%</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {result ? (
          <div className="result-grid">
            <ResultCard title="Truth score" value={`${Math.round((result.truth_score || 0) * 100)}%`} />
            <ResultCard title="Decision" value={result.decision?.decision || "—"} />
            <ResultCard title="Risk" value={result.risk_analysis?.risk_level || "—"} />
            <ResultCard
              title="Report"
              value={
                result.job_id ? (
                  <span>
                    <a href={api.reportUrl(result.job_id)} target="_blank" rel="noreferrer">
                      PDF
                    </a>
                    {" · "}
                    <button type="button" className="linkish" onClick={() => void attestCurrent()}>
                      Attest
                    </button>
                  </span>
                ) : (
                  "—"
                )
              }
            />
          </div>
        ) : null}
      </section>
    </AppShell>
  );
}
