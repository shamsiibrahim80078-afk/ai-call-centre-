import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import {
  bootstrapTelegramWebApp,
  getTelegramInitData,
  getTelegramUser,
  isTelegramMiniApp,
  preferVeridiqDarkInTelegram,
  type TelegramWebAppUser,
} from "../lib/telegramWebApp";

/**
 * Compact console entry for Telegram Mini App (`/mini`).
 * Skips marketing splash; offers Dashboard / Verify / Workforce shortcuts.
 */
export default function MiniAppPage() {
  const [user, setUser] = useState<TelegramWebAppUser | null>(null);
  const [authNote, setAuthNote] = useState<string>("");
  const [inTelegram, setInTelegram] = useState(false);

  useEffect(() => {
    const ok = bootstrapTelegramWebApp();
    preferVeridiqDarkInTelegram();
    setInTelegram(ok || isTelegramMiniApp());
    setUser(getTelegramUser());

    const initData = getTelegramInitData();
    if (!initData) {
      setAuthNote(
        ok
          ? "Opened in Telegram — open via bot Menu so initData is present."
          : "Not inside Telegram WebView. Open from @bot Menu button (HTTPS Mini App URL)."
      );
      return;
    }

    let cancelled = false;
    api
      .telegramWebAppAuth({ init_data: initData, issue_session: true })
      .then((res) => {
        if (cancelled) return;
        if (res.access_token) {
          localStorage.setItem("veridiq_token", res.access_token);
        }
        if (res.user) setUser(res.user as TelegramWebAppUser);
        setAuthNote(
          res.session_user
            ? `Signed in as ${res.session_user.full_name || res.user?.username || "Telegram user"}`
            : "Telegram identity verified."
        );
      })
      .catch((err: Error) => {
        if (!cancelled) setAuthNote(err.message || "WebApp auth failed");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const greeting =
    user?.first_name || user?.username
      ? `Salaam, ${user.first_name || user.username}`
      : "VERIDIQ Mini App";

  return (
    <div className="miniapp-page">
      <header className="miniapp-header">
        <img src="/veridiq-logo.svg" alt="" width={40} height={40} />
        <div>
          <p className="miniapp-eyebrow">VERIDIQ</p>
          <h1>{greeting}</h1>
          <p className="muted miniapp-tag">Truth. Verified. Empowered.</p>
        </div>
      </header>

      <p className="miniapp-auth muted" role="status">
        {authNote || (inTelegram ? "Connecting…" : "Browser preview mode")}
      </p>

      <nav className="miniapp-actions" aria-label="Console shortcuts">
        <Link className="btn btn-primary" to="/dashboard">
          Enter console
        </Link>
        <Link className="btn btn-ghost" to="/dashboard/verify">
          Verify a claim
        </Link>
        <Link className="btn btn-ghost" to="/dashboard/workforce">
          Workforce
        </Link>
        <Link className="btn btn-ghost" to="/dashboard/comms">
          Comms
        </Link>
      </nav>

      <p className="miniapp-hint muted">
        Mini App = frontend HTTPS site inside Telegram. Bot worker (long-poll) stays separate.
      </p>
    </div>
  );
}
