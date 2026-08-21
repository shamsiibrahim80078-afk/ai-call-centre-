"""Firebase — project id status only until a service account is configured."""

from __future__ import annotations

from typing import Any

from veridiq.integrations.base import first_env, status_shape

PLATFORM = "firebase"
DISPLAY = "Firebase"
CATEGORY = "infra"
ENV_VARS = ("VERIDIQ_FIREBASE_PROJECT", "VERIDIQ_FIREBASE_SERVICE_ACCOUNT_JSON")
CAPABILITIES = ["project_status"]
DOCS = "https://firebase.google.com/docs"


def status() -> dict[str, Any]:
    project = first_env("VERIDIQ_FIREBASE_PROJECT", "FIREBASE_PROJECT_ID", "GCLOUD_PROJECT")
    sa = first_env("VERIDIQ_FIREBASE_SERVICE_ACCOUNT_JSON", "GOOGLE_APPLICATION_CREDENTIALS")
    if not project:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message="Set VERIDIQ_FIREBASE_PROJECT (and later a service account) for Firebase.",
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
        )
    if not sa:
        return status_shape(
            PLATFORM,
            DISPLAY,
            CATEGORY,
            status="configuration_required",
            configured=False,
            message=(
                f"Firebase project id set ({project}). Full SDK/Admin access requires a service account "
                "(VERIDIQ_FIREBASE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS)."
            ),
            env_vars=ENV_VARS,
            capabilities=CAPABILITIES,
            docs_url=DOCS,
            extra={"project_id": project, "service_account_set": False},
        )
    return status_shape(
        PLATFORM,
        DISPLAY,
        CATEGORY,
        status="configured",
        configured=True,
        message=f"Firebase project '{project}' + service account path/json present.",
        env_vars=ENV_VARS,
        capabilities=CAPABILITIES + ["admin_sdk"],
        docs_url=DOCS,
        extra={"project_id": project, "service_account_set": True},
    )


def test_connection() -> dict[str, Any]:
    project = first_env("VERIDIQ_FIREBASE_PROJECT", "FIREBASE_PROJECT_ID", "GCLOUD_PROJECT")
    sa = first_env("VERIDIQ_FIREBASE_SERVICE_ACCOUNT_JSON", "GOOGLE_APPLICATION_CREDENTIALS")
    if not project:
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": "Set VERIDIQ_FIREBASE_PROJECT.",
        }
    if not sa:
        return {
            "platform": PLATFORM,
            "status": "configuration_required",
            "ok": False,
            "message": (
                f"Project id '{project}' recorded. No live Firebase Admin call without a service account. "
                "configuration_required until SA is provided."
            ),
            "project_id": project,
        }
    # Do not invent Admin SDK init here — report configured readiness only.
    return {
        "platform": PLATFORM,
        "status": "ok",
        "ok": True,
        "message": f"Firebase project '{project}' has credentials path configured (Admin SDK init deferred).",
        "project_id": project,
    }


def project_status(**_kwargs: Any) -> dict[str, Any]:
    return test_connection()
