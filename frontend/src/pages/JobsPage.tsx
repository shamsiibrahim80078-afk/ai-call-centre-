import { useCallback, useEffect, useState } from "react";
import AppShell, { Metric } from "../components/AppShell";
import { api } from "../api/client";

export default function JobsPage() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [connectors, setConnectors] = useState<any>(null);
  const [jobListings, setJobListings] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [j, c, listings] = await Promise.all([api.jobs(), api.connectors(), api.connectorJobs()]);
      setJobs(j.jobs || []);
      setConnectors(c);
      setJobListings(listings);
    } catch (e: any) {
      setError(e.message || "Failed to load jobs");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const completed = jobs.filter((j) => j.status === "completed").length;
  const active = jobs.filter((j) => j.status === "processing" || j.status === "queued").length;

  return (
    <AppShell title="Jobs" subtitle="Verification jobs and official job-market connectors">
      {error ? <div className="banner error">{error}</div> : null}

      <section className="metrics">
        <Metric label="Verification jobs" value={String(jobs.length)} />
        <Metric label="Active" value={String(active)} />
        <Metric label="Completed" value={String(completed)} />
        <Metric label="Market connector" value={String(jobListings?.status || connectors?.jobs?.status || "—")} />
      </section>

      <section className="panel glass">
        <h2>Recent verification jobs</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th>Truth</th>
                <th>Risk</th>
                <th>Created</th>
                <th>Report</th>
              </tr>
            </thead>
            <tbody>
              {jobs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="muted">
                    No jobs yet — run a verification.
                  </td>
                </tr>
              ) : (
                jobs.map((j) => (
                  <tr key={j.job_uuid}>
                    <td>{j.title}</td>
                    <td>
                      <span className={`pill ${j.status === "completed" ? "ok" : j.status === "failed" ? "bad" : ""}`}>
                        {j.status}
                      </span>
                    </td>
                    <td className="mono">{j.truth_score != null ? `${Math.round(Number(j.truth_score) * 100)}%` : "—"}</td>
                    <td>{j.risk_level || "—"}</td>
                    <td className="mono muted">{j.created_at}</td>
                    <td>
                      {j.status === "completed" ? (
                        <a href={api.reportUrl(j.job_uuid)} target="_blank" rel="noreferrer">
                          PDF
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel glass">
        <h2>Job market connector</h2>
        {jobListings?.status === "ok" ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Company</th>
                  <th>Location</th>
                </tr>
              </thead>
              <tbody>
                {(jobListings.jobs || []).slice(0, 10).map((item: any, i: number) => (
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
                    <td>{item.company || "—"}</td>
                    <td>{item.location || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">
            {jobListings?.message ||
              "Configure an official jobs API provider. Counts are not fabricated when the connector is unavailable."}
          </p>
        )}
      </section>
    </AppShell>
  );
}
