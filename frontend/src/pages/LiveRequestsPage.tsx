import { type FormEvent, useCallback, useEffect, useState } from "react";
import AppShell, { Metric, StatusBanner } from "../components/AppShell";
import WorkflowVisualizer from "../components/WorkflowVisualizer";
import { api, subscribeJobEvents, type JobEvent } from "../api/client";

type Props = {
  title?: string;
  presetKey?: string;
};

export default function LiveRequestsPage({ title = "AI Requests", presetKey }: Props) {
  const [text, setText] = useState(() => {
    if (presetKey) {
      const preset = sessionStorage.getItem(presetKey);
      if (preset) return preset;
    }
    return "Analyze today's crypto market.";
  });
  const [plan, setPlan] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [result, setResult] = useState<any>(null);
  const [depts, setDepts] = useState<any>(null);

  const refreshDepts = useCallback(async () => {
    try {
      setDepts(await api.departments());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    void refreshDepts();
    const id = window.setInterval(() => void refreshDepts(), 4000);
    return () => window.clearInterval(id);
  }, [refreshDepts]);

  useEffect(() => {
    let cancelled = false;
    void api.orchestratorPlan(text).then((p) => {
      if (!cancelled) setPlan(p);
    });
    return () => {
      cancelled = true;
    };
  }, [text]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setEvents([{ stage: "route", message: "User request accepted" }]);
    setResult(null);
    try {
      const out = await api.liveRequest(text.trim(), { async_mode: true });
      setPlan(out.plan || plan);
      if (out.mode === "comms") {
        setResult(out);
        setEvents((prev) => [...prev, { stage: "completed", message: "Communication draft ready (approval required)" }]);
        return;
      }
      if (out.mode === "market") {
        setResult(out.result || out);
        setEvents((prev) => [
          ...prev,
          { stage: "market_plan", message: "Market planner engaged" },
          { stage: "market_evidence", message: "Specialists gathering evidence" },
          { stage: "market_reasoning", message: "Risk synthesis" },
          { stage: "completed", message: "Market brief complete" },
        ]);
        await refreshDepts();
        return;
      }
      const jobUuid = out.job_uuid as string;
      await new Promise<void>((resolve, reject) => {
        const stop = subscribeJobEvents(
          jobUuid,
          (ev) => setEvents((prev) => [...prev.slice(-60), ev]),
          () => {
            stop();
            resolve();
          }
        );
        window.setTimeout(() => {
          stop();
          reject(new Error("Timed out"));
        }, 180000);
      });
      const job = await api.job(jobUuid);
      setResult(job.result || job);
      await refreshDepts();
    } catch (err: any) {
      setError(err.message || "Request failed");
    } finally {
      setBusy(false);
    }
  }

  const waiting = !busy && !result;

  return (
    <AppShell title={title} subtitle="Orchestrator routes work to the right AI department and streams live progress">
      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} idleText="Waiting for Assignment" />

      <section className="metrics">
        <Metric label="Intent" value={plan?.intent || "—"} />
        <Metric label="Department" value={String(plan?.department || "—").replace(/_/g, " ")} />
        <Metric label="Pipeline" value={plan?.pipeline || "—"} />
        <Metric label="Subtasks" value={String(plan?.subtasks?.length ?? 0)} />
      </section>

      <section className="panel glass">
        <h2>Assign work</h2>
        <p className="muted">Examples: Analyze today&apos;s crypto market · Investigate this company · Verify this speech</p>
        <form className="verify-form" onSubmit={onSubmit}>
          <textarea className="field" rows={4} value={text} onChange={(e) => setText(e.target.value)} required />
          <button className="btn btn-primary" type="submit" disabled={busy || !text.trim()}>
            {busy ? "Orchestrating…" : "Run live request"}
          </button>
        </form>
      </section>

      <section className="panel glass">
        <h2>Live workflow</h2>
        <WorkflowVisualizer events={events} active={busy} />
        {events.length > 0 ? (
          <div className="sse-log" aria-live="polite">
            <h3>Event stream</h3>
            <ul>
              {events.slice(-12).map((ev, i) => (
                <li key={`${ev.stage}-${i}`}>
                  <span className="mono">{ev.stage}</span>
                  <span>{ev.message || ev.agent_type || ""}</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {result ? (
          <div className="result-grid" style={{ marginTop: "1rem" }}>
            <div className="result-card">
              <span>Mode</span>
              <strong>{result.mode || plan?.pipeline || "truth"}</strong>
            </div>
            <div className="result-card">
              <span>Confidence</span>
              <strong>
                {typeof result.confidence === "number"
                  ? `${Math.round(result.confidence * 100)}%`
                  : typeof result.truth_score === "number"
                    ? `${Math.round(result.truth_score * 100)}%`
                    : "—"}
              </strong>
            </div>
            <div className="result-card">
              <span>Disclaimer</span>
              <strong style={{ fontSize: "0.85rem", fontWeight: 500 }}>
                {result.disclaimer || "Probabilistic analysis — not a guarantee."}
              </strong>
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel glass">
        <h2>Department status</h2>
        <div className="persona-grid dense">
          {(depts?.departments || []).map((d: any) => (
            <div key={d.id} className="persona-card glass">
              <div>
                <strong>{d.name}</strong>
                <span className="muted">
                  active {d.workload?.active_workers ?? 0} · queue {d.workload?.queue ?? 0}
                </span>
                <span className={`pill ${d.live_metrics?.waiting_for_tasks ? "" : "ok"}`}>
                  {d.live_metrics?.status_label}
                </span>
              </div>
            </div>
          ))}
        </div>
      </section>
    </AppShell>
  );
}
