import { SignedIn, SignedOut, useClerk, useUser } from "@clerk/clerk-react";
import { type FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import AppShell from "../components/AppShell";
import { api, clearSession, saveSession } from "../api/client";
import { isClerkEnabled } from "../lib/clerk";

export default function AccountPage() {
  const clerkOn = isClerkEnabled();

  return (
    <AppShell title="Account" subtitle="Secure access to the VERIDIQ console">
      {clerkOn ? <ClerkAccountPanel /> : <LegacyAccountPanel />}
    </AppShell>
  );
}

function ClerkAccountPanel() {
  const { user, isLoaded } = useUser();
  const { signOut } = useClerk();

  if (!isLoaded) {
    return (
      <section className="panel glass">
        <h2>Session</h2>
        <p className="muted">Loading Clerk session…</p>
      </section>
    );
  }

  async function onSignOut() {
    clearSession();
    await signOut({ redirectUrl: "/" });
    window.dispatchEvent(new Event("veridiq-session"));
  }

  return (
    <section className="panel glass">
      <h2>Session</h2>
      <SignedIn>
        <div className="auth-box">
          <p>
            Signed in with Clerk as{" "}
            <strong>{user?.primaryEmailAddress?.emailAddress || user?.fullName || user?.id}</strong>
          </p>
          <p className="muted">API calls use a VERIDIQ JWT synced from your Clerk session.</p>
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
            <Link className="btn btn-primary" to="/dashboard/settings">
              Open Settings
            </Link>
            <button className="btn btn-ghost" type="button" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        </div>
      </SignedIn>
      <SignedOut>
        <div className="auth-box">
          <p className="muted">You are signed out.</p>
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
            <Link className="btn btn-primary" to="/sign-in">
              Sign in
            </Link>
            <Link className="btn btn-ghost" to="/sign-up">
              Sign up
            </Link>
          </div>
        </div>
      </SignedOut>
    </section>
  );
}

function LegacyAccountPanel() {
  const [email, setEmail] = useState("admin@veridiq.ai");
  const [password, setPassword] = useState("VeridiqAdmin!23");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState<any>(() => {
    try {
      return JSON.parse(localStorage.getItem("veridiq_user") || "null");
    } catch {
      return null;
    }
  });

  async function onLogin(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const out = await api.login(email, password);
      saveSession(out.access_token, out.user);
      setUser(out.user);
    } catch (err: any) {
      setError(err.message || "Login failed");
    } finally {
      setBusy(false);
    }
  }

  function logout() {
    clearSession();
    setUser(null);
  }

  return (
    <>
      {error ? <div className="banner error">{error}</div> : null}
      <section className="panel glass">
        <h2>Session</h2>
        <p className="muted" style={{ marginTop: "0.35rem" }}>
          Clerk keys not loaded — using local FastAPI login. Set{" "}
          <code>VITE_CLERK_PUBLISHABLE_KEY</code> to enable Clerk.
        </p>
        {user ? (
          <div className="auth-box">
            <p>
              Signed in as <strong>{user.email}</strong> ({user.role})
            </p>
            <button className="btn btn-ghost" type="button" onClick={logout}>
              Sign out
            </button>
          </div>
        ) : (
          <form className="auth-form" onSubmit={onLogin}>
            <input className="field" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            <input
              className="field"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <button className="btn btn-primary" type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        )}
      </section>
    </>
  );
}
