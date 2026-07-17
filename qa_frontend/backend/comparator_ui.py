"""Read-only adapter between the QA UI and the Phase 10.3 comparator."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from tb_runner.baseline_repository import BaselineRepository, BaselineRepositoryError
from tb_runner.comparison_input import adapt_approved_baseline, adapt_candidate
from tb_runner.comparison_replay import replay_selected_inputs

from .paths import ROOT_DIR, RUN_LOG_DIR


class ComparatorUiError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class ComparatorUiService:
    """Catalogues immutable inputs and retains reports only for this process."""

    def __init__(self, *, root_dir: Path = ROOT_DIR, run_log_dir: Path = RUN_LOG_DIR) -> None:
        self.root_dir = root_dir
        self.run_log_dir = run_log_dir
        self._reports: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = RLock()

    @property
    def baseline_root(self) -> Path:
        return self.root_dir / "baselines"

    def approved_baselines(self) -> list[dict[str, Any]]:
        if not self.baseline_root.is_dir():
            raise ComparatorUiError("BASELINE_REPOSITORY_UNAVAILABLE", "Approved baseline repository is unavailable.", 503)
        try:
            summaries = BaselineRepository(self.baseline_root).list_baselines(include_inactive=False)
        except BaselineRepositoryError as exc:
            raise ComparatorUiError("BASELINE_REPOSITORY_UNAVAILABLE", "Approved baseline repository is invalid.", 503) from exc
        baselines = []
        for item in summaries:
            fingerprint = item.get("environment_fingerprint", {}).get("fingerprint_source", {}).get("direct", {})
            baselines.append({
                "baseline_id": item["baseline_id"], "revision": item.get("revision"), "state": item.get("state"),
                "approved_at": item.get("approved_at"), "app_package": item.get("app_key"),
                "version": fingerprint.get("target_app_release_train"), "locale": fingerprint.get("locale"),
            })
        if not baselines:
            raise ComparatorUiError("NO_APPROVED_BASELINES", "No approved baselines are available.", 404)
        return sorted(baselines, key=lambda item: (str(item["locale"]), str(item["baseline_id"])))

    def candidates(self) -> list[dict[str, Any]]:
        if not self.run_log_dir.is_dir():
            raise ComparatorUiError("NO_CANDIDATES", "No candidate run artifacts are available.", 404)
        candidates: list[dict[str, Any]] = []
        for path in sorted(self.run_log_dir.rglob("candidate_*.baseline_candidate.json")):
            try:
                candidate = adapt_candidate(path)
            except (OSError, ValueError, KeyError):
                continue
            environment = dict(candidate.environment)
            candidates.append({
                "candidate_id": candidate.source_id,
                "run": path.parent.parent.name,
                "source": path.relative_to(self.run_log_dir).as_posix(),
                "app_package": environment.get("app_package"),
                "version": environment.get("app_version_name"),
                "locale": environment.get("locale"),
            })
        if not candidates:
            raise ComparatorUiError("NO_CANDIDATES", "No readable candidate artifacts are available.", 404)
        return candidates

    def _baseline_input(self, baseline_id: str):
        self.approved_baselines()
        try:
            package = BaselineRepository(self.baseline_root).inspect_baseline(baseline_id)["package_path"]
            return adapt_approved_baseline(self.baseline_root / package)
        except (BaselineRepositoryError, OSError, ValueError, KeyError) as exc:
            raise ComparatorUiError("BASELINE_NOT_FOUND", "Selected approved baseline was not found.", 404) from exc

    def _candidate_input(self, candidate_id: str):
        paths = [self.run_log_dir / item["source"] for item in self.candidates() if item["candidate_id"] == candidate_id]
        if not paths:
            raise ComparatorUiError("CANDIDATE_NOT_FOUND", "Selected candidate was not found.", 404)
        if len(paths) > 1:
            raise ComparatorUiError("AMBIGUOUS_CANDIDATE", "Candidate identifier is not unique; select a newer candidate run.", 409)
        try:
            return adapt_candidate(paths[0])
        except (OSError, ValueError, KeyError) as exc:
            raise ComparatorUiError("DATA_UNAVAILABLE", "Candidate data is no longer readable.", 409) from exc

    def compare(self, *, baseline_id: str, candidate_id: str) -> dict[str, Any]:
        baseline = self._baseline_input(baseline_id)
        candidate = self._candidate_input(candidate_id)
        try:
            replay = replay_selected_inputs(baseline, candidate, repository_root=self.root_dir)
        except Exception as exc:  # Comparator contract failures are presented as non-mutating UI errors.
            raise ComparatorUiError("COMPARISON_UNAVAILABLE", str(exc), 409) from exc
        comparison_id = str(replay.result["comparison_id"])
        entry = {
            "comparison_id": comparison_id,
            "baseline_id": baseline_id,
            "candidate_id": candidate_id,
            "compared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "verdict": replay.result.get("verdict"),
            "result": replay.result,
            "markdown": replay.markdown,
            "canonical_json": replay.canonical_json,
        }
        with self._lock:
            self._reports[comparison_id] = entry
            self._reports.move_to_end(comparison_id)
            while len(self._reports) > 25:
                self._reports.popitem(last=False)
        return self.public_entry(entry, include_result=True)

    @staticmethod
    def public_entry(entry: dict[str, Any], *, include_result: bool = False) -> dict[str, Any]:
        value = {key: entry[key] for key in ("comparison_id", "baseline_id", "candidate_id", "compared_at", "verdict")}
        if include_result:
            value["result"] = entry["result"]
        return value

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self.public_entry(entry) for entry in reversed(self._reports.values())]

    def report(self, comparison_id: str) -> dict[str, Any]:
        with self._lock:
            entry = self._reports.get(comparison_id)
        if entry is None:
            raise ComparatorUiError("COMPARISON_NOT_FOUND", "Comparison result is not available in this server session.", 404)
        return entry

