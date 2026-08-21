import { useAuth, useUser } from "@clerk/clerk-react";
import { useEffect, useRef } from "react";
import { clearSession, hasApiSession, saveSession, api } from "../api/client";
import { isClerkEnabled } from "../lib/clerk";

/**
 * When Clerk signs in, exchange the session JWT for a VERIDIQ access token
 * so existing Authorization: Bearer calls keep working.
 * When Clerk signs out, clear the API JWT so protected API calls stop.
 *
 * Note: avoid a module-level "syncing" mutex — React StrictMode remounts cancel
 * the first run; a mutex would skip the remount and leave no API token.
 *
 * Retries briefly on iat/nbf clock-skew failures (server also allows JWT leeway).
 */
export default function ClerkTokenSync() {
  const enabled = isClerkEnabled();
  if (!enabled) return null;
  return <ClerkTokenSyncInner />;
}

function isClockSkewError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err || "");
  return /not yet valid|iat|nbf|clock/i.test(msg);
}

async function sleep(ms: number) {
  await new Promise((r) => setTimeout(r, ms));
}

function ClerkTokenSyncInner() {
  const { isSignedIn, getToken, isLoaded } = useAuth();
  const { user } = useUser();
  const lastSub = useRef<string | null>(null);

  useEffect(() => {
    if (!isLoaded) return;

    if (!isSignedIn) {
      if (lastSub.current || hasApiSession()) {
        clearSession();
      }
      lastSub.current = null;
      return;
    }

    const sub = user?.id || "signed-in";
    if (lastSub.current === sub && hasApiSession()) return;

    let cancelled = false;
    (async () => {
      const email =
        user?.primaryEmailAddress?.emailAddress ||
        user?.emailAddresses?.[0]?.emailAddress ||
        "";
      const fullName = user?.fullName || [user?.firstName, user?.lastName].filter(Boolean).join(" ");
      const delays = [0, 800, 1600, 3200];
      let lastErr: unknown = null;

      for (let i = 0; i < delays.length; i++) {
        if (cancelled) return;
        if (delays[i] > 0) await sleep(delays[i]);
        if (cancelled) return;
        try {
          const token = await getToken();
          if (!token || cancelled) return;
          const out = await api.clerkSync(token, { email, full_name: fullName });
          if (cancelled) return;
          if (out?.access_token) {
            saveSession(out.access_token, out.user);
            lastSub.current = sub;
            return;
          }
        } catch (err) {
          lastErr = err;
          if (!isClockSkewError(err) || i === delays.length - 1) break;
        }
      }

      if (import.meta.env.DEV && !cancelled && lastErr) {
        console.warn("[VERIDIQ] Clerk→API token sync failed (Clerk UI still works):", lastErr);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [isLoaded, isSignedIn, getToken, user]);

  return null;
}
