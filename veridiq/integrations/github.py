"""GitHub connector — official GitHub REST API via VERIDIQ service layer."""

from __future__ import annotations

import os
from typing import Any, Optional

import requests

from veridiq.integrations.base import status_shape

TOKEN = "VERIDIQ_GITHUB_TOKEN"
ENV_VARS = [TOKEN]
CAPABILITIES = ["whoami", "list_repos", "create_issue (after explicit approval)"]
DOCS = "https://docs.github.com/en/rest"


def status() -> dict[str, Any]:
    if not os.getenv(TOKEN):
        return status_shape(
            "github",
            "GitHub",
            "devtools",
            status="configuration_required",
            configured=False,
            message=f"Set {TOKEN} (fine-grained or classic PAT) for official GitHub API access.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    return status_shape(
        "github",
        "GitHub",
        "devtools",
        status="configured",
        configured=True,
        message="GitHub token present — use /test to verify with a live call.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES,
        docs_url=DOCS,
    )


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.getenv(TOKEN)}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def test_connection() -> dict[str, Any]:
    if not os.getenv(TOKEN):
        return {"platform": "github", "status": "configuration_required", "message": f"Set {TOKEN}."}
    try:
        resp = requests.get("https://api.github.com/user", headers=_headers(), timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "platform": "github",
                "status": "ok",
                "api_response_status": resp.status_code,
                "message": f"Verified GitHub user @{data.get('login')}.",
            }
        return {
            "platform": "github",
            "status": "error",
            "api_response_status": resp.status_code,
            "message": f"GitHub API HTTP {resp.status_code}.",
        }
    except Exception as exc:
        return {"platform": "github", "status": "error", "message": str(exc)[:200]}


def list_repos(*, per_page: int = 10, **_kwargs: Any) -> dict[str, Any]:
    if not os.getenv(TOKEN):
        return {"platform": "github", "status": "configuration_required", "ok": False, "message": f"Set {TOKEN}."}
    try:
        resp = requests.get(
            "https://api.github.com/user/repos",
            headers=_headers(),
            params={"per_page": max(1, min(30, int(per_page))), "sort": "updated"},
            timeout=10,
        )
        if resp.status_code != 200:
            return {
                "platform": "github",
                "status": "error",
                "ok": False,
                "api_response_status": resp.status_code,
                "message": f"GitHub API HTTP {resp.status_code}.",
            }
        repos = [
            {"full_name": r.get("full_name"), "private": r.get("private"), "html_url": r.get("html_url")}
            for r in (resp.json() or [])
        ]
        return {"platform": "github", "status": "ok", "ok": True, "repos": repos, "count": len(repos)}
    except Exception as exc:
        return {"platform": "github", "status": "error", "ok": False, "message": str(exc)[:200]}
