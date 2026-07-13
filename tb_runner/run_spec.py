from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from tb_runner.runtime_config import RUNTIME_CONFIG_PATH_ENV


def resolve_identity_feature_flags(
    *,
    evidence_ledger: bool = False,
    identity_shadow_v2: bool = False,
    traversal_identity_v2: bool = True,
) -> dict[str, bool]:
    traversal = bool(traversal_identity_v2)
    identity = bool(identity_shadow_v2 or traversal)
    evidence = bool(evidence_ledger or identity)
    return {
        "evidence_ledger": evidence,
        "identity_shadow_v2": identity,
        "traversal_identity_v2": traversal,
    }


@dataclass(frozen=True)
class RunSpec:
    serial: str | None = None
    mode: str = "full"
    language_mode: str = "current"
    launch_mode: str = "warm"
    scenario_ids: tuple[str, ...] = ()
    output_dir: str | None = None
    runtime_config_path: str | None = None
    enable_coverage_probe: bool = False
    evidence_ledger: bool = False
    identity_shadow_v2: bool = False
    traversal_identity_v2: bool = True

    @property
    def feature_flags(self) -> dict[str, bool]:
        return resolve_identity_feature_flags(
            evidence_ledger=self.evidence_ledger,
            identity_shadow_v2=self.identity_shadow_v2,
            traversal_identity_v2=self.traversal_identity_v2,
        )

    def build_script_command(self, script_path: str | Path) -> list[str]:
        command = [sys.executable, str(script_path)]
        if self.serial:
            command.extend(["--serial", self.serial])
        if self.output_dir:
            command.extend(["--output-dir", self.output_dir])
        command.extend(["--mode", self.mode])
        command.extend(["--language-mode", self.language_mode])
        command.extend(["--launch-mode", self.launch_mode])
        for scenario_id in self.scenario_ids:
            command.extend(["--scenario", scenario_id])
        return command

    def build_subprocess_env(self, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
        env = dict(os.environ if base_env is None else base_env)
        if self.serial:
            env["ANDROID_SERIAL"] = self.serial
        if self.output_dir:
            env["TB_OUTPUT_DIR"] = self.output_dir
        if self.runtime_config_path:
            env[RUNTIME_CONFIG_PATH_ENV] = self.runtime_config_path
        if self.enable_coverage_probe:
            env["TB_V8_COVERAGE_PROBE"] = "1"
        feature_flags = self.feature_flags
        if feature_flags["evidence_ledger"]:
            env["TB_EVIDENCE_LEDGER_ENABLED"] = "1"
        else:
            env.pop("TB_EVIDENCE_LEDGER_ENABLED", None)
        if feature_flags["identity_shadow_v2"]:
            env["TB_EVIDENCE_IDENTITY_SHADOW_ENABLED"] = "1"
        else:
            env.pop("TB_EVIDENCE_IDENTITY_SHADOW_ENABLED", None)
        if feature_flags["traversal_identity_v2"]:
            env["TB_TRAVERSAL_IDENTITY_V2_ENABLED"] = "1"
        else:
            # Explicitly select the Legacy Compatibility path for this run.
            # This must not inherit a parent process value.
            env["TB_TRAVERSAL_IDENTITY_V2_ENABLED"] = "0"
        return env


@dataclass(frozen=True)
class RunContext:
    spec: RunSpec

    @property
    def serial(self) -> str | None:
        return self.spec.serial

    @property
    def output_dir(self) -> str:
        return self.spec.output_dir or os.environ.get("TB_OUTPUT_DIR", "output")
