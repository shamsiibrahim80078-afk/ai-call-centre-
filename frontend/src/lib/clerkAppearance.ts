/**
 * VERIDIQ Clerk UI appearance (dark brand).
 *
 * Web3 / MetaMask is shown when enabled in Clerk Dashboard →
 * User & Authentication → Web3 → MetaMask. Google / email stay available.
 * Requires the MetaMask browser extension for wallet sign-in.
 */
export const veridiqClerkAppearance = {
  variables: {
    colorPrimary: "#3b82f6",
    colorBackground: "#0f172a",
    colorInputBackground: "#1e293b",
    colorInputText: "#e2e8f0",
    colorText: "#e2e8f0",
    colorTextSecondary: "#94a3b8",
    borderRadius: "0.5rem",
  },
  elements: {
    card: {
      background: "rgba(15, 23, 42, 0.92)",
      border: "1px solid rgba(148, 163, 184, 0.18)",
      boxShadow: "0 18px 48px rgba(0,0,0,0.45)",
    },
    headerTitle: { color: "#f8fafc" },
    headerSubtitle: { color: "#94a3b8" },
    socialButtonsBlockButton: {
      background: "rgba(30, 41, 59, 0.9)",
      border: "1px solid rgba(148, 163, 184, 0.22)",
      color: "#e2e8f0",
    },
    formButtonPrimary: {
      background: "#2563eb",
      "&:hover": { background: "#1d4ed8" },
    },
    footerActionLink: { color: "#60a5fa" },
  },
} as const;

/** Loose type for Clerk appearance props (avoids coupling to @clerk/types package). */
export type VeridiqClerkAppearance = typeof veridiqClerkAppearance;
