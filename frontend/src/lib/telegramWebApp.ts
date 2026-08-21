/**
 * Telegram Mini App (WebApp) helpers.
 * Requires script: https://telegram.org/js/telegram-web-app.js (see index.html).
 */

export type TelegramWebAppUser = {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
  photo_url?: string;
};

export type TelegramThemeParams = {
  bg_color?: string;
  text_color?: string;
  hint_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  secondary_bg_color?: string;
  header_bg_color?: string;
  accent_text_color?: string;
  section_bg_color?: string;
  section_header_text_color?: string;
  subtitle_text_color?: string;
  destructive_text_color?: string;
};

type TelegramWebAppLike = {
  initData?: string;
  initDataUnsafe?: {
    user?: TelegramWebAppUser;
    query_id?: string;
    auth_date?: number;
  };
  version?: string;
  platform?: string;
  colorScheme?: "light" | "dark";
  themeParams?: TelegramThemeParams;
  isExpanded?: boolean;
  ready?: () => void;
  expand?: () => void;
  close?: () => void;
  setHeaderColor?: (color: string) => void;
  setBackgroundColor?: (color: string) => void;
  enableClosingConfirmation?: () => void;
  disableVerticalSwipes?: () => void;
};

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebAppLike };
  }
}

const VERIDIQ_BG = "#05070f";
const VERIDIQ_HEADER = "#0b1224";

export function getTelegramWebApp(): TelegramWebAppLike | null {
  try {
    return window.Telegram?.WebApp ?? null;
  } catch {
    return null;
  }
}

/** True when running inside Telegram's WebView with a real WebApp object. */
export function isTelegramMiniApp(): boolean {
  const wa = getTelegramWebApp();
  if (!wa) return false;
  // initData is empty outside Telegram; presence of platform + version is enough
  // for theming / ready(), but auth needs initData.
  return Boolean(wa.initData || wa.initDataUnsafe?.user || wa.platform);
}

export function getTelegramInitData(): string {
  return (getTelegramWebApp()?.initData || "").trim();
}

export function getTelegramUser(): TelegramWebAppUser | null {
  const user = getTelegramWebApp()?.initDataUnsafe?.user;
  return user && typeof user.id === "number" ? user : null;
}

/** Apply VERIDIQ dark chrome + Telegram theme CSS vars; call ready/expand. */
export function bootstrapTelegramWebApp(): boolean {
  const wa = getTelegramWebApp();
  if (!wa) return false;

  try {
    wa.ready?.();
    wa.expand?.();
  } catch {
    /* older clients */
  }

  try {
    wa.setHeaderColor?.(VERIDIQ_HEADER);
    wa.setBackgroundColor?.(VERIDIQ_BG);
  } catch {
    /* optional */
  }

  applyTelegramTheme(wa.themeParams || {}, wa.colorScheme === "light" ? "light" : "dark");
  document.documentElement.classList.add("telegram-miniapp");
  document.body.classList.add("telegram-miniapp");
  return true;
}

export function applyTelegramTheme(
  params: TelegramThemeParams,
  colorScheme: "light" | "dark" = "dark"
): void {
  const root = document.documentElement;
  root.dataset.telegramColorScheme = colorScheme;
  const map: Record<string, string | undefined> = {
    "--tg-theme-bg-color": params.bg_color || VERIDIQ_BG,
    "--tg-theme-text-color": params.text_color || "#f7f9fc",
    "--tg-theme-hint-color": params.hint_color || "#9aa6bf",
    "--tg-theme-link-color": params.link_color || "#4f8cff",
    "--tg-theme-button-color": params.button_color || "#4f8cff",
    "--tg-theme-button-text-color": params.button_text_color || "#ffffff",
    "--tg-theme-secondary-bg-color": params.secondary_bg_color || VERIDIQ_HEADER,
  };
  for (const [key, value] of Object.entries(map)) {
    if (value) root.style.setProperty(key, value);
  }
}

/** Prefer VERIDIQ dark even when Telegram reports light (console look). */
export function preferVeridiqDarkInTelegram(): void {
  const wa = getTelegramWebApp();
  if (!wa) return;
  try {
    wa.setHeaderColor?.(VERIDIQ_HEADER);
    wa.setBackgroundColor?.(VERIDIQ_BG);
  } catch {
    /* ignore */
  }
  applyTelegramTheme(
    {
      ...(wa.themeParams || {}),
      bg_color: VERIDIQ_BG,
      text_color: "#f7f9fc",
      hint_color: "#9aa6bf",
      link_color: "#4f8cff",
      button_color: "#4f8cff",
      button_text_color: "#ffffff",
      secondary_bg_color: VERIDIQ_HEADER,
    },
    "dark"
  );
}
