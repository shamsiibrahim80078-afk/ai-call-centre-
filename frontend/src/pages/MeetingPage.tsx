import { type FormEvent, useCallback, useEffect, useState } from "react";
import AppShell, { Metric, StatusBanner } from "../components/AppShell";
import { api, subscribeJobEvents, type JobEvent } from "../api/client";

export default function MeetingPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [transcript, setTranscript] = useState(
    "Alice: We closed the acquisition on Friday.\nBob: Revenue was up forty percent in Q2.\nAlice: That figure is confirmed in the board packet."
  );
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [result, setResult] = useState<any>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      setMetrics(await api.meetingMetrics());
    } catch (e: any) {
      setError(e.message || "Failed to load meeting metrics");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(id);
  }, [refresh]);

  async function onAnalyze(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setEvents([]);
    setResult(null);
    try {
      const queued = await api.verify(transcript.trim(), "Meeting analysis", true);
      const jobUuid = queued.job_uuid as string;
      await new Promise<void>((resolve, reject) => {
        const stop = subscribeJobEvents(
          jobUuid,
          (ev) => setEvents((prev) => [...prev.slice(-40), ev]),
          () => {
            stop();
            resolve();
          }
        );
        window.setTimeout(() => {
          stop();
          reject(new Error("Meeting analysis timed out"));
        }, 180000);
      });
      const job = await api.job(jobUuid);
      setResult(job.result || job);
      await refresh();
    } catch (err: any) {
      setError(err.message || "Meeting analysis failed");
    } finally {
      setBusy(false);
    }
  }

  const waiting = Boolean(metrics?.waiting_for_tasks) && !busy;
  const assignments = metrics?.assignments || [];

  return (
    <AppShell title="Meeting Intelligence" subtitle="Live meeting extraction and verification progress">
      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} label={metrics?.status_label} idleText="Waiting for Assignment" />

      <section className="metrics">
        <Metric label="Live meetings" value={String(metrics?.live_meetings ?? 0)} />
        <Metric
          label="Speakers detected"
          value={metrics?.speakers_detected != null ? String(metrics.speakers_detected) : waiting ? "0" : "—"}
        />
        <Metric label="Statements extracted" value={String(metrics?.statements_extracted ?? 0)} />
        <Metric
          label="Verification progress"
          value={`${Math.round((metrics?.verification_progress || 0) * 100)}%`}
        />
      </section>

      <section className="panel glass">
        <h2>Analyze meeting transcript</h2>
        <p className="muted">Runs the real LangGraph pipeline with meeting/timeline agents over SSE.</p>
        <form className="verify-form" onSubmit={onAnalyze}>
          <textarea
            className="field"
            rows={6}
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            required
          />
          <button className="btn btn-primary" type="submit" disabled={busy || !transcript.trim()}>
            {busy ? "Analyzing…" : "Run meeting analysis"}
          </button>
        </form>
        {events.length > 0 ? (
          <div className="sse-log" aria-live="polite">
            <h3>Live progress</h3>
            <ul>
              {events.slice(-10).map((ev, i) => (
                <li key={`${ev.stage}-${i}`}>
                  <span className="mono">{ev.stage}</span>
                  <span>{ev.message || ev.agent_type || ""}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {result ? (
          <p className="muted" style={{ marginTop: "0.85rem" }}>
            Truth score{" "}
            <strong className="mono">
              {typeof result.truth_score === "number" ? `${Math.round(result.truth_score * 100)}%` : "—"}
            </strong>
          </p>
        ) : null}
      </section>

      <section className="panel glass">
        <h2>Active meeting workers</h2>
        {assignments.length === 0 ? (
          <p className="muted waiting-copy">Waiting for Tasks</p>
        ) : (
          <ul className="assignment-list">
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
    </AppShell>
  );
}
