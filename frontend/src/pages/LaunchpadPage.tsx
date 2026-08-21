import { useCallback, useEffect, useMemo, useState } from "react";
import AppShell, { Metric } from "../components/AppShell";
import { api } from "../api/client";
import { formatUsd } from "../lib/format";

function Spark({ points }: { points?: number[] }) {
  const vals = (points || []).filter((n) => Number.isFinite(n));
  if (vals.length < 2) return <div className="launchpad-spark empty" />;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const up = vals[vals.length - 1] >= vals[0];
  return (
    <div className={`launchpad-spark ${up ? "up" : "down"}`}>
      {vals.slice(-24).map((v, i) => (
        <span key={i} style={{ height: `${8 + ((v - min) / range) * 28}px` }} />
      ))}
    </div>
  );
}

export default function LaunchpadPage() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("trending");
  const [selected, setSelected] = useState<any>(null);
  const [chart, setChart] = useState<any>(null);
  const [launchForm, setLaunchForm] = useState({
    token_name: "",
    token_symbol: "",
    network: "Base",
    initial_supply: 1000000,
  });
  const [launchResult, setLaunchResult] = useState<any>(null);
  const [launching, setLaunching] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const snap = await api.launchpad({ q: q || undefined, sort });
      setData(snap);
    } catch (e: any) {
      setError(e.message || "Failed to load launchpad");
    }
  }, [q, sort]);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 12000);
    return () => window.clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    if (!selected?.id || selected.source === "veridiq") {
      setChart(null);
      return;
    }
    let cancelled = false;
    api
      .launchpadChart(selected.id, 1)
      .then((c) => {
        if (!cancelled) setChart(c);
      })
      .catch(() => {
        if (!cancelled) setChart(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const tokens = data?.tokens || [];
  const stream = data?.buy_sell_stream || data?.transactions || [];
  const analytics = data?.analytics || {};

  const chartPoints = useMemo(() => {
    const prices = chart?.history?.prices;
    if (Array.isArray(prices) && prices.length) {
      if (Array.isArray(prices[0])) {
        return prices.map((p: any) => Number(p[1])).filter(Number.isFinite);
      }
      return prices.map((p: any) => Number(p.price ?? p)).filter(Number.isFinite);
    }
    return selected?.sparkline || [];
  }, [chart, selected]);

  async function onLaunch(e: React.FormEvent) {
    e.preventDefault();
    setLaunching(true);
    setLaunchResult(null);
    try {
      const result = await api.launchpadLaunch(launchForm);
      setLaunchResult(result);
      await refresh();
    } catch (err: any) {
      setLaunchResult({ success: false, error: err.message || "Launch failed" });
    } finally {
      setLaunching(false);
    }
  }

  return (
    <AppShell
      title="Token Launchpad"
      subtitle="Live market feed · VERIDIQ launches · charts & wallet activity"
    >
      {error ? <div className="banner error">{error}</div> : null}

      <section className="metrics">
        <Metric label="Feed" value={String(data?.status || "—")} />
        <Metric label="Tokens" value={String(tokens.length)} />
        <Metric label="VERIDIQ launches" value={String(analytics.veridiq_launches ?? "—")} />
        <Metric
          label="Avg 24h"
          value={
            analytics.avg_change_24h != null ? `${Number(analytics.avg_change_24h).toFixed(2)}%` : "—"
          }
        />
      </section>

      <section className="launchpad-toolbar panel glass">
        <input
          className="input"
          placeholder="Search symbol or name…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="input" value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="trending">Trending</option>
          <option value="volume">Volume</option>
          <option value="gainers">Gainers</option>
          <option value="losers">Losers</option>
        </select>
        <button type="button" className="btn ghost" onClick={() => void refresh()}>
          Refresh
        </button>
      </section>

      <div className="launchpad-grid">
        <section className="panel glass launchpad-feed">
          <header className="launchpad-head">
            <h2>Live token feed</h2>
            <p className="muted">CoinGecko public markets + VERIDIQ-originated launches</p>
          </header>
          <div className="launchpad-table-wrap">
            <table className="launchpad-table">
              <thead>
                <tr>
                  <th>Token</th>
                  <th>Price</th>
                  <th>24h</th>
                  <th>Volume</th>
                  <th>Chart</th>
                </tr>
              </thead>
              <tbody>
                {tokens.map((t: any) => {
                  const ch = Number(t.change_24h || 0);
                  return (
                    <tr
                      key={t.id || t.symbol}
                      className={selected?.id === t.id ? "active" : ""}
                      onClick={() => setSelected(t)}
                    >
                      <td>
                        <div className="launchpad-token">
                          {t.image ? <img src={t.image} alt="" width={22} height={22} /> : null}
                          <div>
                            <strong>{t.symbol}</strong>
                            <span className="muted">{t.name}</span>
                          </div>
                        </div>
                      </td>
                      <td className="mono">{formatUsd(t.price)}</td>
                      <td className={ch >= 0 ? "pos" : "neg"}>{ch.toFixed(2)}%</td>
                      <td className="mono">{formatUsd(t.volume_24h)}</td>
                      <td>
                        <Spark points={t.sparkline} />
                      </td>
                    </tr>
                  );
                })}
                {!tokens.length ? (
                  <tr>
                    <td colSpan={5} className="muted">
                      No market data right now — CoinGecko may be unreachable. VERIDIQ launches still
                      appear below when present.
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </section>

        <aside className="launchpad-side">
          <section className="panel glass">
            <h2>Selected analytics</h2>
            {selected ? (
              <>
                <p>
                  <strong>{selected.symbol}</strong> · {selected.name}
                </p>
                <ul className="stat-list">
                  <li>
                    <span>Price</span>
                    <strong className="mono">{formatUsd(selected.price)}</strong>
                  </li>
                  <li>
                    <span>24h</span>
                    <strong className={Number(selected.change_24h) >= 0 ? "pos" : "neg"}>
                      {Number(selected.change_24h || 0).toFixed(2)}%
                    </strong>
                  </li>
                  <li>
                    <span>Market cap</span>
                    <strong className="mono">{formatUsd(selected.market_cap)}</strong>
                  </li>
                </ul>
                <div className="launchpad-chart">
                  <Spark points={chartPoints} />
                </div>
              </>
            ) : (
              <p className="muted">Select a token to inspect live chart analytics.</p>
            )}
          </section>

          <section className="panel glass">
            <h2>Trending</h2>
            <ul className="launchpad-mini-list">
              {(data?.trending || []).slice(0, 8).map((t: any) => (
                <li key={t.id || t.symbol}>
                  <span>{t.symbol}</span>
                  <strong className={Number(t.change_24h) >= 0 ? "pos" : "neg"}>
                    {Number(t.change_24h || 0).toFixed(2)}%
                  </strong>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel glass">
            <h2>Buy / Sell stream</h2>
            <p className="muted tiny">Market ticks from live 24h direction — not fabricated DEX fills.</p>
            <ul className="launchpad-stream">
              {stream.slice(0, 14).map((tx: any, i: number) => (
                <li key={`${tx.symbol}-${i}`}>
                  <span className={tx.side === "buy" ? "pos" : "neg"}>{tx.side}</span>
                  <strong>{tx.symbol}</strong>
                  <em className="mono">{formatUsd(tx.price)}</em>
                </li>
              ))}
            </ul>
          </section>
        </aside>
      </div>

      <div className="launchpad-grid secondary">
        <section className="panel glass">
          <h2>New / VERIDIQ launches</h2>
          <ul className="launchpad-mini-list">
            {(data?.new_launches || []).slice(0, 16).map((t: any) => (
              <li key={t.id || `${t.symbol}-${t.network}`}>
                <span>
                  {t.symbol} {t.network ? `· ${t.network}` : ""}
                </span>
                <strong>{t.source || t.status}</strong>
              </li>
            ))}
            {!(data?.new_launches || []).length ? <li className="muted">No launches yet.</li> : null}
          </ul>
        </section>

        <section className="panel glass">
          <h2>Wallet activity</h2>
          <ul className="launchpad-mini-list mono-list">
            {(data?.wallet_activity || []).slice(0, 12).map((w: any, i: number) => (
              <li key={`${w.tx_hash}-${i}`}>
                <span className="mono truncate">{w.wallet || "—"}</span>
                <strong>{w.symbol}</strong>
              </li>
            ))}
            {!(data?.wallet_activity || []).length ? (
              <li className="muted">Wallet activity appears after VERIDIQ token launches.</li>
            ) : null}
          </ul>
        </section>

        <section className="panel glass">
          <h2>Launch from VERIDIQ</h2>
          <p className="muted">
            Uses the existing audited ERC-20 pipeline (`crypto_launchpad`). Simulated broadcast until
            live chain deploy keys are configured.
          </p>
          <form className="launchpad-form" onSubmit={onLaunch}>
            <input
              className="input"
              placeholder="Token name"
              value={launchForm.token_name}
              onChange={(e) => setLaunchForm((f) => ({ ...f, token_name: e.target.value }))}
              required
            />
            <input
              className="input"
              placeholder="Symbol"
              value={launchForm.token_symbol}
              onChange={(e) => setLaunchForm((f) => ({ ...f, token_symbol: e.target.value.toUpperCase() }))}
              required
            />
            <select
              className="input"
              value={launchForm.network}
              onChange={(e) => setLaunchForm((f) => ({ ...f, network: e.target.value }))}
            >
              <option>Base</option>
              <option>Ethereum</option>
              <option>Solana</option>
            </select>
            <button className="btn primary" type="submit" disabled={launching}>
              {launching ? "Launching…" : "Launch token"}
            </button>
          </form>
          {launchResult ? (
            <pre className="code-block">{JSON.stringify(launchResult, null, 2)}</pre>
          ) : null}
        </section>
      </div>
    </AppShell>
  );
}
