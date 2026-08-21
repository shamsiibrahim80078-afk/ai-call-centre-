import { type FormEvent, useCallback, useEffect, useState } from "react";
import AppShell, { Metric, StatusBanner } from "../components/AppShell";
import { api } from "../api/client";

export default function MarketIntelPage() {
  const [market, setMarket] = useState<any>(null);
  const [history, setHistory] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [analysis, setAnalysis] = useState<any>(null);
  const [prompt, setPrompt] = useState("Analyze today's crypto market.");

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [m, h] = await Promise.all([api.market(), api.marketHistory("bitcoin", 7)]);
      setMarket(m);
      setHistory(h);
    } catch (e: any) {
      setError(e.message || "Failed to load market data");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(id);
  }, [refresh]);

  async function onAnalyze(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = await api.liveRequest(prompt, { async_mode: false, coin_id: "bitcoin" });
      setAnalysis(out.result || out);
      await refresh();
    } catch (err: any) {
      setError(err.message || "Market analysis failed");
    } finally {
      setBusy(false);
    }
  }

  const assets = market?.assets || [];
  const waiting = market?.status !== "ok" && !assets.length;

  return (
    <AppShell title="Market Intelligence Center" subtitle="Official CoinGecko market data + AI analyst team">
      {error ? <div className="banner error">{error}</div> : null}
      {waiting ? <StatusBanner waiting /> : null}

      <section className="metrics">
        <Metric label="Provider" value={String(market?.provider || "—")} />
        <Metric label="Assets" value={String(market?.count ?? 0)} />
        <Metric label="Status" value={String(market?.status || "—")} />
        <Metric
          label="BTC trend"
          value={String(history?.indicators?.trend_bias || "—")}
        />
      </section>

      <section className="panel glass">
        <h2>Live prices</h2>
        <p className="muted">{market?.disclaimer}</p>
        {market?.status !== "ok" ? (
          <p className="muted">{market?.message || "Market feed unavailable — no fabricated prices."}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Asset</th>
                  <th>Price</th>
                  <th>24h</th>
                  <th>Volume</th>
                  <th>Market cap</th>
                </tr>
              </thead>
              <tbody>
                {assets.slice(0, 15).map((a: any) => (
                  <tr key={a.id}>
                    <td>
                      {a.symbol} <span className="muted">{a.name}</span>
                    </td>
                    <td className="mono">{a.price != null ? `$${Number(a.price).toLocaleString()}` : "—"}</td>
                    <td className="mono">{a.change_24h_pct != null ? `${Number(a.change_24h_pct).toFixed(2)}%` : "—"}</td>
                    <td className="mono">{a.volume_24h != null ? Number(a.volume_24h).toLocaleString() : "—"}</td>
                    <td className="mono">{a.market_cap != null ? Number(a.market_cap).toLocaleString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel glass">
        <h2>Dominance · Volatility · Liquidity</h2>
        <div className="metrics" style={{ marginBottom: 0 }}>
          <Metric
            label="Top dominance"
            value={
              market?.dominance?.items?.[0]
                ? `${market.dominance.items[0].symbol} ${market.dominance.items[0].dominance_pct}%`
                : "—"
            }
          />
          <Metric
            label="Avg |Δ| 24h"
            value={
              market?.volatility?.avg_abs_change_24h != null
                ? `${market.volatility.avg_abs_change_24h}%`
                : "—"
            }
          />
          <Metric
            label="Sample volume"
            value={
              market?.liquidity?.total_volume_24h != null
                ? Number(market.liquidity.total_volume_24h).toLocaleString()
                : "—"
            }
          />
          <Metric label="Binance public" value={String(market?.binance_public?.status || "—")} />
        </div>
      </section>

      <section className="panel glass">
        <h2>Binance public tickers</h2>
        {market?.binance_public?.status !== "ok" ? (
          <p className="muted">{market?.binance_public?.message || "Unavailable — no fabricated tickers."}</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Price</th>
                  <th>24h</th>
                  <th>Quote volume</th>
                </tr>
              </thead>
              <tbody>
                {(market?.binance_public?.tickers || []).map((t: any) => (
                  <tr key={t.symbol}>
                    <td className="mono">{t.symbol}</td>
                    <td className="mono">{Number(t.price).toLocaleString()}</td>
                    <td className="mono">{Number(t.change_24h_pct).toFixed(2)}%</td>
                    <td className="mono">{Number(t.quote_volume).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="panel glass">
        <h2>Heatmap (24h %)</h2>
        <div className="heat-grid">
          {(market?.heatmap || []).slice(0, 20).map((h: any) => {
            const ch = Number(h.change_24h_pct || 0);
            const bg =
              ch > 0 ? `rgba(61,214,140,${Math.min(0.55, Math.abs(ch) / 12)})` : `rgba(255,92,122,${Math.min(0.55, Math.abs(ch) / 12)})`;
            return (
              <div key={h.symbol} className="heat-cell" style={{ background: bg }}>
                <strong>{h.symbol}</strong>
                <span className="mono">{ch.toFixed(2)}%</span>
              </div>
            );
          })}
        </div>
      </section>

      <section className="panel glass">
        <h2>Technical indicators (BTC 7d)</h2>
        <ul className="stat-list">
          <li>
            <span>SMA short</span>
            <strong className="mono">{history?.indicators?.sma_short ?? "—"}</strong>
          </li>
          <li>
            <span>SMA long</span>
            <strong className="mono">{history?.indicators?.sma_long ?? "—"}</strong>
          </li>
          <li>
            <span>Momentum</span>
            <strong className="mono">{history?.indicators?.momentum ?? "—"}</strong>
          </li>
        </ul>
        <div className="sparkline" aria-hidden>
          {(history?.prices || []).slice(-40).map((p: any, i: number) => {
            const prices = (history?.prices || []).map((x: any) => x.price);
            const min = Math.min(...prices);
            const max = Math.max(...prices);
            const h = max === min ? 50 : ((p.price - min) / (max - min)) * 100;
            return <span key={i} style={{ height: `${Math.max(8, h)}%` }} />;
          })}
        </div>
      </section>

      <section className="panel glass">
        <h2>AI Market Analyst Team</h2>
        <form className="verify-form" onSubmit={onAnalyze}>
          <textarea className="field" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Analysts collaborating…" : "Run market analysis"}
          </button>
        </form>
        {analysis ? (
          <div style={{ marginTop: "1rem" }}>
            <p>
              Confidence{" "}
              <strong className="mono">
                {typeof analysis.confidence === "number" ? `${Math.round(analysis.confidence * 100)}%` : "—"}
              </strong>
            </p>
            <p className="muted">{analysis.disclaimer}</p>
            <h3 className="subh">Risks</h3>
            <ul className="plain-list">
              {(analysis.risks || []).slice(0, 6).map((r: string) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            <h3 className="subh">Alternative scenarios</h3>
            <ul className="plain-list">
              {(analysis.alternative_scenarios || []).slice(0, 6).map((r: string) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            <h3 className="subh">Sources</h3>
            <ul className="plain-list mono">
              {(analysis.sources || []).map((r: string) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="panel glass">
        <h2>Connectors</h2>
        <ul className="stat-list">
          {Object.entries(market?.connectors || {}).map(([k, v]: [string, any]) =>
            typeof v === "object" && v?.status ? (
              <li key={k}>
                <span>{k}</span>
                <strong className="mono">{v.status}</strong>
              </li>
            ) : null
          )}
        </ul>
        <p className="muted">
          Optional keys: VERIDIQ_CMC_API_KEY, VERIDIQ_BINANCE_API_KEY / VERIDIQ_BINANCE_API_SECRET. CoinGecko public
          markets work without a key.
        </p>
      </section>
    </AppShell>
  );
}
