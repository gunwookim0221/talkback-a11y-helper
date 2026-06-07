from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from talkback_lib import A11yAdbClient
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


def probe_plugin(request: PluginProbeRequest, *, client: A11yAdbClient | None = None) -> dict[str, Any]:
    payload = request.model_dump() if hasattr(request, "model_dump") else request.dict()
    return start_plugin_probe(payload, client=client or A11yAdbClient())
