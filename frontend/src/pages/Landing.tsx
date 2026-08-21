import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import Splash from "../components/Splash";
import Home from "./Home";
import {
  bootstrapTelegramWebApp,
  isTelegramMiniApp,
  preferVeridiqDarkInTelegram,
} from "../lib/telegramWebApp";

/** Root ("/"): cinematic splash → marketing Home. Full ops console lives at /dashboard.
 * Inside Telegram Mini App: skip splash and go straight to /mini console entry.
 */
export default function Landing() {
  const [telegramMode] = useState(() => {
    const ok = bootstrapTelegramWebApp();
    if (ok || isTelegramMiniApp()) {
      preferVeridiqDarkInTelegram();
      return true;
    }
    return false;
  });

  const [showSplash, setShowSplash] = useState(() => {
    if (telegramMode) return false;
    return !sessionStorage.getItem("veridiq_splash_seen");
  });

  useEffect(() => {
    if (!telegramMode) return;
    preferVeridiqDarkInTelegram();
  }, [telegramMode]);

  if (telegramMode) {
    return <Navigate to="/mini" replace />;
  }

  function finishSplash() {
    sessionStorage.setItem("veridiq_splash_seen", "1");
    setShowSplash(false);
  }

  if (showSplash) {
    return <Splash onComplete={finishSplash} />;
  }

  return <Home />;
}
