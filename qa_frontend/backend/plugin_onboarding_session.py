from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .paths import OUTPUT_DIR, ROOT_DIR
from tb_runner.plugin_onboarding_session import (
    create_onboarding_session,
    execute_onboarding_rollback,
    get_onboarding_session,
    list_onboarding_sessions,
    preview_onboarding_rollback,
    restore_onboarding_session,
    save_onboarding_step,
)

SESSION_ROOT = OUTPUT_DIR / "plugin_onboarding_sessions"


class PluginOnboardingCardRequest(BaseModel):
    label: str = ""
    stable_label: str = ""
    type: str = ""
    existing_scenario_id: str = ""


class PluginOnboardingSessionCreateRequest(BaseModel):
    card: PluginOnboardingCardRequest


class PluginOnboardingSessionStepRequest(BaseModel):
    step: str = ""
    status: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class PluginOnboardingRollbackExecuteRequest(BaseModel):
    confirm: bool = False


def create_session(request: PluginOnboardingSessionCreateRequest) -> dict[str, Any]:
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    return create_onboarding_session(payload.get("card") or {}, SESSION_ROOT)


def save_session_step(session_id: str, request: PluginOnboardingSessionStepRequest) -> dict[str, Any]:
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    return save_onboarding_step(
        session_id,
        payload.get("step") or "",
        payload.get("status") or "",
        payload.get("payload") or {},
        SESSION_ROOT,
    )


def get_session(session_id: str) -> dict[str, Any]:
    return get_onboarding_session(session_id, SESSION_ROOT)


def list_sessions(limit: int = 20) -> dict[str, Any]:
    return list_onboarding_sessions(SESSION_ROOT, limit=limit)


def restore_session(session_id: str) -> dict[str, Any]:
    return restore_onboarding_session(session_id, SESSION_ROOT)


def preview_session_rollback(session_id: str) -> dict[str, Any]:
    return preview_onboarding_rollback(session_id, SESSION_ROOT, ROOT_DIR)


def execute_session_rollback(session_id: str, request: PluginOnboardingRollbackExecuteRequest) -> dict[str, Any]:
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    return execute_onboarding_rollback(
        session_id,
        bool(payload.get("confirm")),
        SESSION_ROOT,
        ROOT_DIR,
    )
