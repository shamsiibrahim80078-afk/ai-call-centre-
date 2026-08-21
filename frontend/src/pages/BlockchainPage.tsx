import { useCallback, useEffect, useState } from "react";
import AppShell, { Metric } from "../components/AppShell";
import { api } from "../api/client";
import { fetchChainStatus } from "../lib/chainClient";

export default function BlockchainPage() {
  const [status, setStatus] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [s, c] = await Promise.all([api.blockchainStatus(), fetchChainStatus().catch(() => null)]);
      setStatus({ ...s, client: c });
    } catch (e: any) {
      setError(e.message || "Failed to load blockchain status");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 8000);
    return () => window.clearInterval(id);
  }, [refresh]);

  return (
    <AppShell title="Blockchain Readiness" subtitle="Modular EVM integration — configure addresses to go live">
      {error ? <div className="banner error">{error}</div> : null}
      <section className="metrics">
        <Metric label="Mode" value={String(status?.mode || "—")} />
        <Metric label="Ready" value={String(status?.ready ?? "—")} />
        <Metric label="Network" value={String(status?.network?.name || status?.network || "—")} />
        <Metric label="Attestation" value={status?.contracts?.TruthAttestation?.configured ? "configured" : "pending"} />
      </section>
      <section className="panel glass">
        <h2>Configuration</h2>
        <p className="muted">
          Contracts are not auto-deployed. Set VERIDIQ_RPC_URL and VERIDIQ_CONTRACT_* environment variables when addresses
          are available. Frontend ethers helpers remain optional.
        </p>
        <ul className="stat-list">
          <li>
            <span>RPC</span>
            <strong className="mono">{status?.network?.rpc_url || "—"}</strong>
          </li>
          <li>
            <span>Event listeners</span>
            <strong>Ready</strong>
          </li>
          <li>
            <span>Transaction service</span>
            <strong>Ready</strong>
          </li>
          <li>
            <span>ABI registry</span>
            <strong>Ready</strong>
          </li>
        </ul>
      </section>
    </AppShell>
  );
}
