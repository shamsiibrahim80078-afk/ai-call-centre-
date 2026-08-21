import { SignUp } from "@clerk/clerk-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { isClerkEnabled } from "../lib/clerk";
import { veridiqClerkAppearance } from "../lib/clerkAppearance";
import { hasMetaMaskProvider, METAMASK_DOWNLOAD_URL } from "../lib/metamaskHint";

/**
 * Clerk Sign-up — Google, email, and MetaMask (when Web3 is enabled in Dashboard).
 * Operator: Clerk Dashboard → User & Authentication → Web3 → enable MetaMask.
 */
export default function SignUpPage() {
  const [showMetaMaskTip, setShowMetaMaskTip] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      setShowMetaMaskTip(!hasMetaMaskProvider());
    }, 400);
    return () => window.clearTimeout(t);
  }, []);

  if (!isClerkEnabled()) {
    return (
      <div className="clerk-auth-page">
        <div className="clerk-auth-panel glass">
          <h1>Sign up</h1>
          <p className="muted">
            Clerk is not configured. Set <code>VITE_CLERK_PUBLISHABLE_KEY</code> in the root{" "}
            <code>.env</code>, then restart Vite.
          </p>
          <Link className="btn btn-primary" to="/dashboard/account">
            Use local account login
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="clerk-auth-page">
      <div className="clerk-auth-brand">
        <Link to="/" className="clerk-auth-logo">
          <img src="/veridiq-logo.svg" alt="" width={36} height={36} />
          <span>VERIDIQ</span>
        </Link>
      </div>
      <p className="clerk-auth-hint muted">
        Create an account with Google, email, or MetaMask (when enabled in Clerk).
      </p>
      {showMetaMaskTip ? (
        <p className="clerk-auth-hint clerk-auth-metamask-tip muted">
          MetaMask not detected. Install the extension from{" "}
          <a href={METAMASK_DOWNLOAD_URL} target="_blank" rel="noreferrer">
            metamask.io/download
          </a>
          , then refresh and try again. Google and email still work without it.
        </p>
      ) : null}
      <SignUp
        routing="path"
        path="/sign-up"
        signInUrl="/sign-in"
        forceRedirectUrl="/dashboard"
        fallbackRedirectUrl="/dashboard"
        appearance={veridiqClerkAppearance}
      />
    </div>
  );
}
