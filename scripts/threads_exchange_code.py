"""Exchange a Threads OAuth authorization code for ACCESS_TOKEN + USER_ID.

Loads APP_ID / APP_SECRET / REDIRECT_URI from gitignored .env.
Does not publish. Optionally writes TOKEN + USER_ID back into .env.

Usage:
  python scripts/threads_exchange_code.py --print-url
  python scripts/threads_exchange_code.py <authorization_code>
  python scripts/threads_exchange_code.py <authorization_code> --write-env
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

from veridiq.integrations import threads  # noqa: E402


def _upsert_env(path: Path, updates: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = text.splitlines()
    keys = set(updates)
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        raw = line.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k = raw.split("=", 1)[0].strip()
            if k in keys:
                out.append(f"{k}={updates[k]}")
                seen.add(k)
                continue
        out.append(line)
    for k, v in updates.items():
        if k not in seen:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Threads OAuth code -> access token")
    parser.add_argument("code", nargs="?", help="Authorization code from redirect URL (?code=...)")
    parser.add_argument("--print-url", action="store_true", help="Print authorize URL and exit")
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="Write VERIDIQ_THREADS_ACCESS_TOKEN + VERIDIQ_THREADS_USER_ID into .env",
    )
    parser.add_argument(
        "--short-lived",
        action="store_true",
        help="Skip long-lived token upgrade (default upgrades when possible)",
    )
    args = parser.parse_args()

    if args.print_url or not args.code:
        try:
            url = threads.authorize_url()
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print("AUTHORIZE_URL:")
        print(url)
        print()
        print("1. In Meta App Dashboard, whitelist Authorize callback / Valid OAuth Redirect URI exactly:")
        print(f"   {threads.redirect_uri()}")
        print("   Desktop bypass: turn Native or desktop app? ON and use")
        print("   https://www.facebook.com/connect/login_success.html (must match .env REDIRECT_URI).")
        print("   Also paste the same URI into Facebook Login -> Settings -> Valid OAuth Redirect URIs.")
        print("   Keep Client OAuth Login + Web OAuth Login ON.")
        print("2. Open the URL above, approve scopes threads_basic,threads_content_publish,threads_manage_replies.")
        print("3. After redirect, copy ?code= from the address bar (login_success.html or /oauth/threads/callback).")
        print("4. Run:  python scripts/threads_exchange_code.py <code> --write-env")
        if not args.code:
            return 0

    code = args.code.strip()
    # Allow pasting a full redirect URL
    m = re.search(r"[?&]code=([^&#]+)", code)
    if m:
        code = m.group(1)

    result = threads.exchange_code(code, long_lived=not args.short_lived)
    if result.get("status") != "ok":
        print(f"ERROR: {result.get('message')}", file=sys.stderr)
        return 1

    token = result["access_token"]
    user_id = result.get("user_id")
    print("OK - code exchanged.")
    print(f"  long_lived: {result.get('long_lived')}")
    if result.get("expires_in") is not None:
        print(f"  expires_in: {result.get('expires_in')}")
    if result.get("long_lived_warning"):
        print(f"  warning: {result['long_lived_warning']}")
    if user_id:
        print(f"  user_id: {user_id}")
    else:
        print("  user_id: (not in token response - run GET /me after setting token)")

    print()
    print("Add to .env (gitignored):")
    print(f"  VERIDIQ_THREADS_ACCESS_TOKEN={token}")
    if user_id:
        print(f"  VERIDIQ_THREADS_USER_ID={user_id}")

    if args.write_env:
        updates = {threads.ACCESS_TOKEN: token}
        if user_id:
            updates[threads.THREADS_USER_ID] = str(user_id)
        _upsert_env(_env, updates)
        print()
        print(f"Wrote {', '.join(updates)} into {_env}")
        print("Restart the backend, then test: integrations -> threads -> test (no live post yet).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
