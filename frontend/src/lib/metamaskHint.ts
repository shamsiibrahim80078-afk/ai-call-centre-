/**
 * Soft MetaMask availability check for auth page tips.
 * Does not call ethereum.request — only reads whether a provider is injected.
 */
export function hasMetaMaskProvider(): boolean {
  if (typeof window === "undefined") return false;
  const eth = (window as unknown as { ethereum?: { isMetaMask?: boolean; providers?: unknown[] } })
    .ethereum;
  if (!eth) return false;
  if (eth.isMetaMask) return true;
  // Some multi-wallet injectors expose MetaMask in providers[]
  const providers = eth.providers;
  if (Array.isArray(providers)) {
    return providers.some((p) => Boolean((p as { isMetaMask?: boolean })?.isMetaMask));
  }
  return false;
}

export const METAMASK_DOWNLOAD_URL = "https://metamask.io/download/";
