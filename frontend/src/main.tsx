import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import ClerkTokenSync from "./components/ClerkTokenSync";
import { VeridiqClerkProvider } from "./lib/clerk";
import { installWalletNoiseFilter } from "./lib/walletNoise";
import "./index.css";

// After Vite client: quiet unsolicited MetaMask inject spam only.
// Does not wrap ethereum or block Clerk MetaMask sign-in button.
installWalletNoiseFilter();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <VeridiqClerkProvider>
        <ClerkTokenSync />
        <App />
      </VeridiqClerkProvider>
    </BrowserRouter>
  </StrictMode>
);
