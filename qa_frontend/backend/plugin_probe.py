from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from talkback_lib import A11yAdbClient
from qa_frontend.backend.preflight import dismiss_samsung_account_popup
from tb_runner.plugin_probe import start_plugin_probe


class PluginProbeCardRequest(BaseModel):
    id: str = ""
    label: str = ""
    stable_label: str = ""
    type: str = ""
    source: str = ""
    bounds: str = ""
    resource_id: str = ""
    existing_scenario_id: str = ""


class PluginProbeRequest(BaseModel):
    card: PluginProbeCardRequest
    max_probe_steps: int = 5
    include_xml: bool = True
    include_helper_dump: bool = True
    serial: str | None = None


def _client_adb_runner(client: A11yAdbClient, serial: str | None):
    run_fn = getattr(client, "_run", None)

    def _runner(args: list[str], _timeout: float) -> dict[str, object]:
        if not callable(run_fn):
            return {"ok": False, "status": "error", "error": "client_run_not_supported"}
        try:
            stdout = run_fn(args, dev=serial)
            return {"ok": True, "status": "ok", "stdout": stdout, "stderr": ""}
        except Exception as exc:
            return {"ok": False, "status": "error", "error": str(exc), "stdout": "", "stderr": str(exc)}

    return _runner


def probe_plugin(request: PluginProbeRequest, *, client: A11yAdbClient | None = None) -> dict[str, Any]:
    client = client or A11yAdbClient()
    popup_status = dismiss_samsung_account_popup(_client_adb_runner(client, request.serial))
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    result = start_plugin_probe(payload, client=client)
    if popup_status.get("popup_detected") and not popup_status.get("popup_dismissed"):
        diagnostics = result.setdefault("diagnostics", {})
        warnings = diagnostics.setdefault("warnings", [])
        if isinstance(warnings, list):
            warnings.append("samsung_account_popup_detected_but_not_dismissed")
    return result
