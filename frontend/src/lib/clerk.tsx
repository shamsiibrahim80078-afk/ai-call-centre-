import { ClerkProvider } from "@clerk/clerk-react";
import type { ReactNode } from "react";
import { veridiqClerkAppearance } from "./clerkAppearance";

/** Publishable key from Vite env (root .env via envDir). */
export function clerkPublishableKey(): string {
  return (
    (import.meta.env.VITE_CLERK_PUBLISHABLE_KEY as string | undefined) ||
    (import.meta.env.VERIDIQ_CLERK_PUBLISHABLE_KEY as string | undefined) ||
    ""
  ).trim();
}

export type ClerkKeyMode = "test" | "live" | "missing" | "invalid";

/** Detect Clerk key environment. Never invent live keys — operators must paste pk_live_/sk_live_ from Dashboard. */
export function clerkKeyMode(pk = clerkPublishableKey()): ClerkKeyMode {
  if (!pk) return "missing";
  if (pk.startsWith("pk_test_")) return "test";
  if (pk.startsWith("pk_live_")) return "live";
  return "invalid";
}

export function isClerkEnabled(): boolean {
  const mode = clerkKeyMode();
  return mode === "test" || mode === "live";
}

export function isClerkDevelopment(): boolean {
  return clerkKeyMode() === "test";
}

/**
 * ClerkProvider for VERIDIQ.
 * Development keys (pk_test_) always log Clerk's production warning — expected for local/dev.
 * Production deploys require a Clerk Production instance + pk_live_ / sk_live_ (see .env.example).
 */
export function VeridiqClerkProvider({ children }: { children: ReactNode }) {
  const pk = clerkPublishableKey();
  const mode = clerkKeyMode(pk);
  if (mode !== "test" && mode !== "live") {
    return <>{children}</>;
  }

  if (import.meta.env.DEV && mode === "test") {
    // One-time friendly note — Clerk still emits its own development-keys warning (cannot suppress).
    const flag = "__veridiq_clerk_dev_note__";
    if (typeof window !== "undefined" && !(window as unknown as Record<string, boolean>)[flag]) {
      (window as unknown as Record<string, boolean>)[flag] = true;
      console.info(
        "[VERIDIQ] Clerk is using development keys (pk_test_). Local sign-in works; production deploys need pk_live_/sk_live_ from Clerk Dashboard → API Keys."
      );
    }
  }

  return (
    <ClerkProvider
      publishableKey={pk}
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
      signInFallbackRedirectUrl="/dashboard"
      signUpFallbackRedirectUrl="/dashboard"
      afterSignOutUrl="/"
      appearance={veridiqClerkAppearance}
    >
      {children}
    </ClerkProvider>
  );
}
