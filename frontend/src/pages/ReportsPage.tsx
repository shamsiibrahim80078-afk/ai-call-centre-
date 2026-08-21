import { useCallback, useEffect, useState } from "react";
import AppShell, { Metric } from "../components/AppShell";
import { api } from "../api/client";

export default function ReportsPage() {
  const [metrics, setMetrics] = useState<any>(null);
  const [chain, setChain] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [m, c] = await Promise.all([api.reportsMetrics(), api.blockchainStatus()]);
      setMetrics(m);
      setChain(c);
    } catch (e: any) {
      setError(e.message || "Failed to load reports");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(id);
  }, [refresh]);

  return (
    <AppShell title="Reports" subtitle="Truth reports, exports, and blockchain-ready attestation">
      {error ? <div className="banner error">{error}</div> : null}

      <section className="metrics">
        <Metric label="Reports generated" value={String(metrics?.reports_generated ?? 0)} />
        <Metric label="Pending reports" value={String(metrics?.pending_reports ?? 0)} />
        <Metric label="Blockchain-ready" value={String(metrics?.blockchain_ready_reports ?? 0)} />
        <Metric label="Chain mode" value={String(chain?.mode || "—")} />
      </section>

      <section className="panel glass">
        <h2>Export history</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Completed</th>
                <th>PDF</th>
              </tr>
            </thead>
            <tbody>
              {(metrics?.export_history || []).length === 0 ? (
                <tr>
                  <td colSpan={3} className="muted">
                    No reports yet.
                  </td>
                </tr>
              ) : (
                (metrics?.export_history || []).map((r: any) => (
                  <tr key={r.job_uuid}>
                    <td>{r.title || r.job_uuid}</td>
                    <td className="mono muted">{r.completed_at || "—"}</td>
                    <td>
                      <a href={api.reportUrl(r.job_uuid)} target="_blank" rel="noreferrer">
                        Download
                      </a>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </AppShell>
  );
}
