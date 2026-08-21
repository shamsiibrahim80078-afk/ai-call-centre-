import path from "node:path";
import { fileURLToPath } from "node:url";
import { createLogger, defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** Drop unsolicited MetaMask inject noise that Vite forwards to the terminal (not user login). */
const WALLET_NOISE =
  /Failed to connect to MetaMask|Error restoring session|chrome-extension:\/+nkbihfbeogaeaoehlefnkodbefgpgknn|Could not establish connection\. Receiving end does not exist/i;

function filterWalletNoiseLogger(): ReturnType<typeof createLogger> {
  const logger = createLogger();
  const wrap =
    (fn: (msg: string, options?: object) => void) =>
    (msg: string, options?: object) => {
      if (WALLET_NOISE.test(msg)) return;
      fn(msg, options);
    };
  logger.info = wrap(logger.info.bind(logger));
  logger.warn = wrap(logger.warn.bind(logger));
  logger.error = wrap(logger.error.bind(logger));
  logger.warnOnce = wrap(logger.warnOnce.bind(logger));
  return logger;
}

export default defineConfig({
  plugins: [react()],
  customLogger: filterWalletNoiseLogger(),
  // Load VITE_* from repo-root .env (same file as FastAPI)
  envDir: rootDir,
  envPrefix: ["VITE_", "VERIDIQ_CLERK_PUBLISHABLE"],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // Meta OAuth via ngrok / Cloudflare quick tunnels
    allowedHosts: [
      ".ngrok-free.app",
      ".ngrok.app",
      ".ngrok.io",
      ".trycloudflare.com",
      "localhost",
    ],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8002",
        changeOrigin: true,
        // Short POSTs + poll GETs; keep generous for safety
        timeout: 180_000,
        proxyTimeout: 180_000,
      },
    },
  },
});
