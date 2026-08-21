import { UserProfile, useAuth, useClerk, useUser } from "@clerk/clerk-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import AppShell from "../components/AppShell";
import { api, clearSession } from "../api/client";
import { isClerkEnabled } from "../lib/clerk";
import { veridiqClerkAppearance } from "../lib/clerkAppearance";

/**
 * Platform Settings: account/auth (Clerk Google) + integration checklist.
 * Route: /dashboard/settings (also linked from Home AuthNav when signed in).
 */
export default function SettingsPage() {
  return (
    <AppShell title="Settings" subtitle="Account, sign-out, and integration checklist">
      {isClerkEnabled() ? <ClerkAccountSettings /> : <LegacyAccountSettings />}
      <IntegrationChecklist />
    </AppShell>
  );
}

function ClerkAccountSettings() {
  const { isLoaded: authLoaded, isSignedIn } = useAuth();
  const { user, isLoaded } = useUser();
  const { signOut, openUserProfile } = useClerk();
  const [showProfile, setShowProfile] = useState(false);

  const email =
    user?.primaryEmailAddress?.emailAddress ||
    user?.emailAddresses?.[0]?.emailAddress ||
    "—";
  const provider =
    user?.externalAccounts?.find((a) => a.provider === "google")?.provider ||
    user?.externalAccounts?.[0]?.provider ||
    (user?.passwordEnabled ? "email" : "clerk");

  async function onSignOut() {
    clearSession();
    await signOut({ redirectUrl: "/" });
    window.dispatchEvent(new Event("veridiq-session"));
  }

  if (!authLoaded || !isLoaded) {
    return (
      <section className="panel glass">
        <h2>Account</h2>
        <p className="muted">Loading session…</p>
      </section>
    );
  }

  if (!isSignedIn) {
    return (
      <section className="panel glass settings-account">
        <h2>Account</h2>
        <div className="auth-box">
          <p className="muted">You are signed out.</p>
          <div className="settings-account-actions">
            <Link className="btn btn-primary" to="/sign-in">
              Sign in
            </Link>
            <Link className="btn btn-ghost" to="/sign-up">
              Sign up
            </Link>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="panel glass settings-account">
      <h2>Account</h2>
      <div className="auth-box">
        <p>
          Signed in as <strong>{email}</strong>
        </p>
        <p className="muted">
          Provider: <span className="mono">{String(provider)}</span>
          {user?.fullName ? (
            <>
              {" "}
              · Name: <strong>{user.fullName}</strong>
            </>
          ) : null}
        </p>
        <p className="muted">
          Sign-in options: Google, email, or MetaMask (when Web3 is enabled in Clerk Dashboard and the
          MetaMask extension is installed).
        </p>
        <div className="settings-account-actions">
          <button
            className="btn btn-primary"
            type="button"
            onClick={() => {
              try {
                openUserProfile?.();
              } catch {
                setShowProfile(true);
              }
            }}
          >
            Manage account
          </button>
          <button className="btn btn-ghost" type="button" onClick={() => setShowProfile((v) => !v)}>
            {showProfile ? "Hide profile" : "Switch Google account"}
          </button>
          <button className="btn btn-ghost" type="button" onClick={() => void onSignOut()}>
            Sign out
          </button>
        </div>
        {showProfile ? (
          <div className="settings-user-profile">
            <p className="muted">
              To use a different Google account: <strong>Sign out</strong>, then Sign in and pick another
              Google identity. Or update connected accounts below.
            </p>
            <UserProfile
              routing="hash"
              appearance={{
                ...veridiqClerkAppearance,
                elements: {
                  ...veridiqClerkAppearance.elements,
                  rootBox: { width: "100%" },
                  card: {
                    ...veridiqClerkAppearance.elements.card,
                    width: "100%",
                    maxWidth: "100%",
                  },
                },
              }}
            />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function LegacyAccountSettings() {
  return (
    <section className="panel glass">
      <h2>Account</h2>
      <p className="muted">
        Clerk is not configured. Use{" "}
        <Link className="mono" to="/dashboard/account">
          /dashboard/account
        </Link>{" "}
        for local login, or set <code>VITE_CLERK_PUBLISHABLE_KEY</code>.
      </p>
    </section>
  );
}

function IntegrationChecklist() {
  const [connectors, setConnectors] = useState<any>(null);
  const [market, setMarket] = useState<any>(null);
  const [chain, setChain] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [c, m, b] = await Promise.all([api.connectors(), api.market(), api.blockchainStatus()]);
      setConnectors(c);
      setMarket(m);
      setChain(b);
    } catch (e: any) {
      setError(e.message || "Failed to load settings");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const rows = [
    {
      key: "VERIDIQ_NEWSAPI_KEY",
      status: connectors?.news?.status || "—",
      note: "Official NewsAPI headlines",
    },
    {
      key: "VERIDIQ_CMC_API_KEY",
      status: market?.connectors?.coinmarketcap?.status || "—",
      note: "CoinMarketCap (CoinGecko works without a key)",
    },
    {
      key: "VERIDIQ_BINANCE_API_KEY",
      status: "optional",
      note: "Authenticated Binance — public ticker works without keys",
    },
    {
      key: "VERIDIQ_MEXC_API_KEY",
      status: market?.connectors?.mexc?.status || "configuration_required",
      note: "MEXC official authenticated APIs",
    },
    {
      key: "VERIDIQ_CONTRACT_* / VERIDIQ_RPC_URL",
      status: chain?.ready ? "ready" : "pending",
      note: "Blockchain attestation when contracts are configured",
    },
  ];

  return (
    <>
      {error ? <div className="banner error">{error}</div> : null}
      <section className="panel glass">
        <h2>Environment checklist</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Variable</th>
                <th>Status</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="mono">{r.key}</td>
                  <td>
                    <span className="pill">{String(r.status)}</span>
                  </td>
                  <td className="muted">{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted" style={{ marginTop: "1rem" }}>
          See <span className="mono">.env.example</span> for the full local configuration template.
        </p>
      </section>
    </>
  );
}
