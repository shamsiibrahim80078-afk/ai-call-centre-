import { type FormEvent, useCallback, useEffect, useState } from "react";
import AppShell, { Metric, StatusBanner } from "../components/AppShell";
import { api, subscribeJobEvents, type JobEvent } from "../api/client";

export default function NewsPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [news, setNews] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [claim, setClaim] = useState("Major outlets reported that the acquisition closed last Friday.");
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [result, setResult] = useState<any>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [m, n] = await Promise.all([api.newsMetrics(), api.connectorNews()]);
      setMetrics(m);
      setNews(n);
    } catch (e: any) {
      setError(e.message || "Failed to load news metrics");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(id);
  }, [refresh]);

  async function onVerifyNews(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setEvents([]);
    setResult(null);
    try {
      const queued = await api.verify(claim.trim(), "News verification", true);
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
          reject(new Error("News verification timed out"));
        }, 180000);
      });
      const job = await api.job(jobUuid);
      setResult(job.result || job);
      await refresh();
    } catch (err: any) {
      setError(err.message || "News verification failed");
    } finally {
      setBusy(false);
    }
  }

  const waiting = Boolean(metrics?.waiting_for_tasks) && !busy;
  const connector = metrics?.connector || news || {};

  return (
    <AppShell title="News Intelligence" subtitle="Live news analysis metrics and official API connectors">
      {error ? <div className="banner error">{error}</div> : null}
      <StatusBanner waiting={waiting} idleText="Waiting for Assignment" />

      <section className="metrics">
        <Metric label="Active analyses" value={String(metrics?.active_news_analyses ?? 0)} />
        <Metric label="Sources checked" value={String(metrics?.sources_checked ?? 0)} />
        <Metric label="Articles processed" value={String(metrics?.articles_processed ?? 0)} />
        <Metric label="Connector" value={String(connector?.status || "—")} />
      </section>

      <section className="panel glass">
        <h2>Verify a news claim</h2>
        <p className="muted">Runs news/web-search agents through LangGraph with live SSE progress.</p>
        <form className="verify-form" onSubmit={onVerifyNews}>
          <textarea className="field" rows={4} value={claim} onChange={(e) => setClaim(e.target.value)} required />
          <button className="btn btn-primary" type="submit" disabled={busy || !claim.trim()}>
            {busy ? "Analyzing…" : "Run news analysis"}
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
        <h2>Data connector</h2>
        {connector?.status === "ok" ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Source</th>
                  <th>Published</th>
                </tr>
              </thead>
              <tbody>
                {(connector.articles || news?.articles || []).slice(0, 12).map((item: any, i: number) => (
                  <tr key={item.url || i}>
                    <td>
                      {item.url ? (
                        <a href={item.url} target="_blank" rel="noreferrer">
                          {item.title}
                        </a>
                      ) : (
                        item.title
                      )}
                    </td>
                    <td>{item.source || "—"}</td>
                    <td className="mono muted">{item.published_at || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">
            {connector?.message ||
              "NewsAPI configuration required (set VERIDIQ_NEWSAPI_KEY). No fabricated article counts are shown."}
          </p>
        )}
      </section>
    </AppShell>
  );
}
