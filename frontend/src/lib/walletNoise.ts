/**
 * Quiet *unsolicited* MetaMask / extension console noise.
 *
 * MetaMask injects into every page and often emits
 * "Failed to connect to MetaMask" / "Error restoring session" on reload —
 * especially after Clerk Google OAuth redirects. Vite forwards both
 * `unhandledrejection` and `console.warn` to the terminal.
 *
 * IMPORTANT: This filter never wraps `window.ethereum`, never calls or
 * blocks `ethereum.request`, and must not interfere with intentional
 * MetaMask connect from Clerk Sign-in / Sign-up. User-initiated wallet
 * errors (missing extension after click, user rejection) are left alone
 * for Clerk's own UI; only inject/spam patterns are silenced.
 */

const EVENTS_FLAG = "__veridiq_wallet_noise_events__";
const CONSOLE_FLAG = "__veridiq_wallet_noise_console__";

/** MetaMask extension id — Vite stack lines sometimes use chrome-extension:/ (one slash). */
const METAMASK_EXT =
  /chrome-extension:\/+nkbihfbeogaeaoehlefnkodbefgpgknn/i;

/**
 * Unsolicited inject spam only — safe to silence on unhandledrejection/error.
 * Do NOT include user-facing Clerk Web3 messages here (missing extension after
 * click, user rejected) so intentional MetaMask login is not disrupted.
 */
const UNSOLICITED_NOISE =
  /Error restoring session|Failed to connect to MetaMask|Could not establish connection\. Receiving end does not exist/i;

/** Broader patterns for console-only (keeps Vite terminal quiet). */
const CONSOLE_NOISE =
  /Error restoring session|Failed to connect to MetaMask|Could not establish connection\. Receiving end does not exist|MetaMask extension not found|Web3 Wallet extension cannot be found|install one to continue/i;

function collectText(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  const parts: string[] = [];
  const err = value as {
    message?: unknown;
    stack?: unknown;
    reason?: unknown;
    data?: unknown;
    code?: unknown;
    name?: unknown;
  };
  if (err.message != null) parts.push(String(err.message));
  if (err.name != null) parts.push(String(err.name));
  if (err.stack != null) parts.push(String(err.stack));
  if (err.reason != null && err.reason !== value) parts.push(collectText(err.reason));
  if (err.data != null && err.data !== value) parts.push(collectText(err.data));
  if (err.code != null) parts.push(String(err.code));
  try {
    parts.push(String(value));
  } catch {
    /* ignore */
  }
  return parts.join("\n");
}

/** True for unsolicited inject spam (event filters). */
export function isWalletNoise(value: unknown): boolean {
  const text = collectText(value);
  if (!text) return false;
  if (UNSOLICITED_NOISE.test(text)) return true;
  // Extension stack noise from inpage restore — not from Clerk button clicks.
  if (
    METAMASK_EXT.test(text) &&
    /Error restoring session|Failed to connect|inpage|contentscript/i.test(text)
  ) {
    return true;
  }
  return false;
}

function isConsoleWalletNoise(value: unknown): boolean {
  const text = collectText(value);
  if (!text) return false;
  if (CONSOLE_NOISE.test(text)) return true;
  if (METAMASK_EXT.test(text) && /connect|MetaMask|ethereum|inpage|restoring session/i.test(text)) {
    return true;
  }
  return false;
}

function silenceEvent(event: Event) {
  event.preventDefault();
  event.stopImmediatePropagation();
}

function installEventFilters() {
  const w = window as unknown as Record<string, boolean>;
  if (w[EVENTS_FLAG]) return;
  w[EVENTS_FLAG] = true;

  window.addEventListener(
    "unhandledrejection",
    (event) => {
      if (isWalletNoise(event.reason)) silenceEvent(event);
    },
    true
  );

  window.addEventListener(
    "rejectionhandled",
    (event) => {
      if (isWalletNoise(event.reason)) silenceEvent(event);
    },
    true
  );

  window.addEventListener(
    "error",
    (event) => {
      if (isWalletNoise(event.error) || isWalletNoise(event.message)) {
        silenceEvent(event);
      }
    },
    true
  );
}

function shouldDropConsoleArgs(args: unknown[]): boolean {
  if (args.some((a) => isConsoleWalletNoise(a))) return true;
  const joined = args.map((a) => collectText(a)).join(" ");
  if (
    /\[vite\].*\[(?:Unhandled rejection|console\.(?:warn|error))\]/i.test(joined) &&
    (CONSOLE_NOISE.test(joined) || METAMASK_EXT.test(joined))
  ) {
    return true;
  }
  return false;
}

/**
 * Always re-apply so this wrap sits *outside* Vite's console interceptor
 * (which registers when /@vite/client loads, after the index.html inline script).
 */
function installConsoleFilters() {
  const w = window as unknown as Record<string, boolean | undefined>;
  const outer = window as unknown as { __veridiq_console_outer__?: boolean };
  if (w[CONSOLE_FLAG] && outer.__veridiq_console_outer__) return;

  (["warn", "error"] as const).forEach((method) => {
    const original = console[method].bind(console);
    console[method] = (...args: unknown[]) => {
      if (shouldDropConsoleArgs(args)) return;
      original(...args);
    };
  });

  w[CONSOLE_FLAG] = true;
  outer.__veridiq_console_outer__ = true;
}

/**
 * Install noise filters. Safe to call from index.html (early) and main.tsx (after Vite).
 * Never proxies ethereum / MetaMask — Sign-in MetaMask button stays fully usable.
 */
export function installWalletNoiseFilter() {
  if (typeof window === "undefined") return;
  installEventFilters();
  installConsoleFilters();
}
