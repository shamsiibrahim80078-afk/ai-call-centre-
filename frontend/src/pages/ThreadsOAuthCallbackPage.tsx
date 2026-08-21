import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";

type ExchangeResult = {
  status: string;
  message?: string;
  access_token?: string;
  user_id?: string | null;
  long_lived?: boolean;
  expires_in?: number;
  wrote_env?: boolean;
  long_lived_warning?: string;
};

/**
 * Public Meta Threads OAuth callback — no auth required.
 * Meta redirects here with ?code=... (or ?error=...).
 * Paste this exact path into Meta Authorize callback URL / Valid OAuth Redirect URIs
 * (via ngrok HTTPS), matching VERIDIQ_THREADS_REDIRECT_URI.
 */
export default function ThreadsOAuthCallbackPage() {
  const [params] = useSearchParams();
  const code = (params.get("code") || "").replace(/#_+$/, "").trim();
  const error = params.get("error");
  const errorDescription = params.get("error_description");
  const [copied, setCopied] = useState(false);
  const [exchanging, setExchanging] = useState(false);
  const [exchange, setExchange] = useState<ExchangeResult | null>(null);

  useEffect(() => {
    document.title = "Threads OAuth — Veridiq";
  }, []);

  async function copyCode() {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* ignore */
    }
  }

  async function runExchange(writeEnv: boolean) {
    if (!code) return;
    setExchanging(true);
    setExchange(null);
    try {
      const result = (await api.threadsOAuthExchange({
        code,
        write_env: writeEnv,
      })) as ExchangeResult;
      setExchange(result);
    } catch (err) {
      setExchange({
        status: "error",
        message: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setExchanging(false);
    }
  }

  return (
    <div className="oauth-callback-page">
      <div className="oauth-callback-panel">
        <p className="oauth-callback-brand">Veridiq</p>
        <h1>Threads OAuth callback</h1>

        {error ? (
          <div className="oauth-callback-error" role="alert">
            <p>
              <strong>Error:</strong> {error}
            </p>
            {errorDescription ? <p className="muted">{errorDescription}</p> : null}
          </div>
        ) : null}

        {!error && !code ? (
          <p className="muted">
            No <code>code</code> in the URL. Complete the Meta authorize flow, or open the authorize
            URL with redirect_uri pointing at this page.
          </p>
        ) : null}

        {code ? (
          <>
            <p className="muted">Authorization code received. Copy it, or exchange it into your local .env.</p>
            <label className="oauth-callback-label" htmlFor="threads-oauth-code">
              Authorization code
            </label>
            <textarea
              id="threads-oauth-code"
              className="oauth-callback-code"
              readOnly
              rows={3}
              value={code}
              onFocus={(e) => e.target.select()}
            />
            <div className="oauth-callback-actions">
              <button type="button" className="btn btn-primary" onClick={copyCode}>
                {copied ? "Copied" : "Copy code"}
              </button>
              <button
                type="button"
                className="btn"
                disabled={exchanging}
                onClick={() => runExchange(false)}
              >
                {exchanging ? "Exchanging…" : "Exchange only"}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={exchanging}
                onClick={() => runExchange(true)}
              >
                {exchanging ? "Exchanging…" : "Exchange + write .env"}
              </button>
            </div>
            <p className="muted oauth-callback-hint">
              CLI alternative:{" "}
              <code>python scripts/threads_exchange_code.py &lt;code&gt; --write-env</code>
            </p>
          </>
        ) : null}

        {exchange ? (
          <div
            className={
              exchange.status === "ok" ? "oauth-callback-ok" : "oauth-callback-error"
            }
            role="status"
          >
            <p>
              <strong>Status:</strong> {exchange.status}
              {exchange.wrote_env ? " (wrote .env)" : ""}
            </p>
            {exchange.message ? <p className="muted">{exchange.message}</p> : null}
            {exchange.user_id ? (
              <p>
                <code>VERIDIQ_THREADS_USER_ID</code> = {exchange.user_id}
              </p>
            ) : null}
            {exchange.access_token ? (
              <p className="muted">
                Token received{exchange.long_lived ? " (long-lived)" : ""}. Restart the backend,
                then Integrations → Threads → test.
              </p>
            ) : null}
            {exchange.long_lived_warning ? (
              <p className="muted">{exchange.long_lived_warning}</p>
            ) : null}
          </div>
        ) : null}

        <p className="oauth-callback-footer">
          <Link to="/dashboard/integrations">Integrations</Link>
        </p>
      </div>
    </div>
  );
}
