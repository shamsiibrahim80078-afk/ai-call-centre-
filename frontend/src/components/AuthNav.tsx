import { useAuth, useClerk, useUser } from "@clerk/clerk-react";
import { Link } from "react-router-dom";
import { useSyncExternalStore } from "react";
import { clearSession } from "../api/client";
import { isClerkEnabled } from "../lib/clerk";

function readLegacyUser(): { email?: string; full_name?: string } | null {
  try {
    return JSON.parse(localStorage.getItem("veridiq_user") || "null");
  } catch {
    return null;
  }
}

function subscribeLegacySession(onStoreChange: () => void) {
  const handler = (e: StorageEvent) => {
    if (!e.key || e.key === "veridiq_user" || e.key === "veridiq_token") onStoreChange();
  };
  window.addEventListener("storage", handler);
  window.addEventListener("veridiq-session", onStoreChange as EventListener);
  return () => {
    window.removeEventListener("storage", handler);
    window.removeEventListener("veridiq-session", onStoreChange as EventListener);
  };
}

/**
 * Compact auth CTAs for marketing Home + AppShell header.
 *
 * Important: do NOT use <SignedOut> alone — while Clerk is loading, SignedOut
 * treats the user as signed-out and flash-shows Sign in/Sign up even when a
 * session exists. Gate on useAuth().isLoaded + isSignedIn instead.
 */
export default function AuthNav({ className = "" }: { className?: string }) {
  if (isClerkEnabled()) {
    return <ClerkAuthNav className={className} />;
  }
  return <LegacyAuthNav className={className} />;
}

function ClerkAuthNav({ className = "" }: { className?: string }) {
  const { isLoaded, isSignedIn } = useAuth();

  if (!isLoaded) {
    return (
      <div className={`auth-nav ${className}`.trim()} aria-busy="true">
        <span className="auth-nav-loading muted">…</span>
      </div>
    );
  }

  if (isSignedIn) {
    return (
      <div className={`auth-nav ${className}`.trim()}>
        <ClerkSignedInNav />
      </div>
    );
  }

  return (
    <div className={`auth-nav ${className}`.trim()}>
      <Link className="btn btn-ghost" to="/sign-in">
        Sign in
      </Link>
      <Link className="btn btn-ghost" to="/sign-up">
        Sign up
      </Link>
    </div>
  );
}

function ClerkSignedInNav() {
  const { user, isLoaded } = useUser();
  const { signOut } = useClerk();
  const label =
    user?.primaryEmailAddress?.emailAddress ||
    user?.fullName ||
    user?.username ||
    "Account";

  async function onSignOut() {
    clearSession();
    await signOut({ redirectUrl: "/" });
    window.dispatchEvent(new Event("veridiq-session"));
  }

  return (
    <>
      <Link className="btn btn-ghost auth-nav-account" to="/dashboard/settings" title={label}>
        {isLoaded ? truncateLabel(label) : "…"}
      </Link>
      <Link className="btn btn-ghost" to="/dashboard/settings">
        Settings
      </Link>
      <button className="btn btn-ghost" type="button" onClick={() => void onSignOut()}>
        Sign out
      </button>
    </>
  );
}

function LegacyAuthNav({ className = "" }: { className?: string }) {
  const user = useSyncExternalStore(subscribeLegacySession, readLegacyUser, () => null);

  if (user) {
    return (
      <div className={`auth-nav ${className}`.trim()}>
        <Link className="btn btn-ghost auth-nav-account" to="/dashboard/settings">
          {truncateLabel(user.full_name || user.email || "Account")}
        </Link>
        <Link className="btn btn-ghost" to="/dashboard/settings">
          Settings
        </Link>
        <button
          className="btn btn-ghost"
          type="button"
          onClick={() => {
            clearSession();
            window.dispatchEvent(new Event("veridiq-session"));
          }}
        >
          Sign out
        </button>
      </div>
    );
  }

  return (
    <div className={`auth-nav ${className}`.trim()}>
      <Link className="btn btn-ghost" to="/sign-in">
        Sign in
      </Link>
      <Link className="btn btn-ghost" to="/sign-up">
        Sign up
      </Link>
    </div>
  );
}

function truncateLabel(value: string, max = 22) {
  const s = (value || "").trim();
  if (s.length <= max) return s;
  return `${s.slice(0, max - 1)}…`;
}
