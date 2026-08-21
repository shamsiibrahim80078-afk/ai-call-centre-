/**
 * Ethers.js-ready blockchain client for VERIDIQ.
 * Uses env-configured RPC addresses only — never auto-connects MetaMask / window.ethereum.
 * Browser wallet connect must be an explicit user action on a dedicated UI (not wired yet).
 * Install ethers when enabling live RPC reads: npm i ethers
 */
const API_BASE = import.meta.env.VITE_API_BASE || "";

export type ChainStatus = {
  ready: boolean;
  mode: string;
  network?: { name?: string; chain_id?: number; rpc_url?: string };
  contracts?: Record<string, { address: string | null; configured: boolean }>;
};

export async function fetchChainStatus(): Promise<ChainStatus> {
  const res = await fetch(`${API_BASE}/api/v1/blockchain/status`);
  if (!res.ok) throw new Error(`blockchain status ${res.status}`);
  return res.json();
}

/**
 * Lazy ethers JsonRpcProvider (HTTP RPC only).
 * Intentionally does NOT use BrowserProvider / eth_requestAccounts — that would spam
 * MetaMask on every page load. Call only from explicit "Connect wallet" UI if added later.
 */
export async function getEthersProvider(rpcUrl?: string) {
  try {
    const ethersMod = await import(/* @vite-ignore */ "ethers").catch(() => null);
    if (!ethersMod?.JsonRpcProvider) {
      return {
        available: false,
        reason: "Install ethers and set VITE_RPC_URL / contract env vars to enable live reads.",
      };
    }
    const url = rpcUrl || import.meta.env.VITE_RPC_URL;
    if (!url) throw new Error("VITE_RPC_URL or rpcUrl required");
    // JsonRpcProvider = remote RPC. Do not pass window.ethereum here.
    return new ethersMod.JsonRpcProvider(url);
  } catch (err) {
    return {
      available: false,
      reason: "Install ethers and set VITE_RPC_URL / contract env vars to enable live reads.",
      error: String(err),
    };
  }
}

export function contractAddressFromEnv(name: string): string | undefined {
  const key = `VITE_CONTRACT_${name.toUpperCase()}`;
  return (import.meta.env as Record<string, string | undefined>)[key];
}
