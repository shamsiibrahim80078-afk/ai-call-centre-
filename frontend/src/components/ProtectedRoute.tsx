import { useAuth } from "@clerk/clerk-react";
import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { isClerkEnabled } from "../lib/clerk";

/** Soft-protect dashboard: require Clerk session when Clerk is configured. */
export default function ProtectedRoute({ children }: { children: ReactNode }) {
  if (!isClerkEnabled()) {
    return <>{children}</>;
  }
  return <ClerkGate>{children}</ClerkGate>;
}

function ClerkGate({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn } = useAuth();
  const location = useLocation();

  if (!isLoaded) {
    return (
      <div className="clerk-auth-page">
        <p className="muted">Checking session…</p>
      </div>
    );
  }

  if (!isSignedIn) {
    const redirect = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/sign-in?redirect_url=${redirect}`} replace />;
  }

  return <>{children}</>;
}
