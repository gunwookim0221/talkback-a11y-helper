"""Read-only adapter between the QA UI and the Phase 10.3 comparator."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import json
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
            repository = BaselineRepository(self.baseline_root)
            summaries = repository.list_baselines(include_inactive=False)
            enriched: list[dict[str, Any]] = []
            for summary in summaries:
                item = dict(summary)
                package = repository.inspect_baseline(str(summary["baseline_id"]))["baseline"]
                item["source_candidate_id"] = package.get("source_candidate_id")
                item["source_run_id"] = package.get("source_run_id")
                item["source_batch_id"] = package.get("source_batch_id")
                enriched.append(item)
            summaries = enriched
        except BaselineRepositoryError as exc:
            raise ComparatorUiError("BASELINE_REPOSITORY_UNAVAILABLE", "Approved baseline repository is invalid.", 503) from exc
        baselines = []
        for item in summaries:
            fingerprint = item.get("environment_fingerprint", {}).get("fingerprint_source", {}).get("direct", {})
            baselines.append({
                "baseline_id": item["baseline_id"], "revision": item.get("revision"), "state": item.get("state"),
                "approved_at": item.get("approved_at"), "app_package": item.get("app_key"),
                "version": fingerprint.get("target_app_release_train"), "locale": fingerprint.get("locale"),
                "source_candidate_id": item.get("source_candidate_id"),
                "source_run_id": item.get("source_run_id"), "source_batch_id": item.get("source_batch_id"),
            })
        if not baselines:
            raise ComparatorUiError("NO_APPROVED_BASELINES", "No approved baselines are available.", 404)
        return sorted(baselines, key=lambda item: (str(item["locale"]), str(item["baseline_id"])))

    def candidates(self) -> list[dict[str, Any]]:
        if not self.run_log_dir.is_dir():
            raise ComparatorUiError("NO_CANDIDATES", "No candidate run artifacts are available.", 404)
        candidates: list[dict[str, Any]] = []
        approved_sources = {
            str(item.get("source_candidate_id")): item
            for item in self._approved_source_summaries()
            if item.get("source_candidate_id")
        }
        for path in sorted(self.run_log_dir.rglob("candidate_*.baseline_candidate.json")):
            try:
                candidate = adapt_candidate(path)
                metadata = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, KeyError):
                continue
            environment = dict(candidate.environment)
            contract = metadata.get("comparison_contract", {})
            scenario_set = contract.get("scenario_set") or {}
            run_kind = scenario_set.get("run_kind") or contract.get("scenario_set", {}).get("run_kind")
            repository = contract.get("repository") or {}
            eligibility = metadata.get("approval_eligibility") or {}
            approval_state = metadata.get("approval_state")
            source_status, source_status_label = self._source_status(
                candidate_id=candidate.source_id,
                source_run_id=metadata.get("source_run_id"),
                source_batch_id=metadata.get("source_batch_id"),
                approval_state=approval_state,
                eligible=eligibility.get("eligible"),
                approved_source=approved_sources.get(candidate.source_id),
            )
            blocking_reasons = list(eligibility.get("reasons") or [])
            if repository.get("dirty") is True and "DIRTY" not in blocking_reasons:
                blocking_reasons.insert(0, "DIRTY")
            if run_kind in {"TARGETED", "SMOKE"} and "SMOKE" not in blocking_reasons:
                blocking_reasons.append("SMOKE" if run_kind == "SMOKE" or metadata.get("source_batch", {}).get("mode") == "smoke" else "TARGETED")
            approved_source = approved_sources.get(candidate.source_id)
            candidates.append({
                "candidate_id": candidate.source_id,
                "run": path.parent.parent.name,
                "source": path.relative_to(self.run_log_dir).as_posix(),
                "app_package": environment.get("app_package"),
                "version": environment.get("app_version_name"),
                "locale": environment.get("locale"),
                "source_status": source_status,
                "source_status_label": source_status_label,
                "eligibility": eligibility.get("eligible"),
                "run_kind": run_kind,
                "dirty": repository.get("dirty"),
                "approved_baseline_id": approved_source.get("baseline_id") if approved_source else None,
                "blocking_reasons": blocking_reasons,
            })
        if not candidates:
            raise ComparatorUiError("NO_CANDIDATES", "No readable candidate artifacts are available.", 404)
        return candidates

    def _approved_source_summaries(self) -> list[dict[str, Any]]:
        if not self.baseline_root.is_dir():
            return []
        try:
            repository = BaselineRepository(self.baseline_root)
            summaries = repository.list_baselines(include_inactive=False)
            enriched: list[dict[str, Any]] = []
            for summary in summaries:
                item = dict(summary)
                package = repository.inspect_baseline(str(summary["baseline_id"]))["baseline"]
                item["source_candidate_id"] = package.get("source_candidate_id")
                item["source_run_id"] = package.get("source_run_id")
                item["source_batch_id"] = package.get("source_batch_id")
                enriched.append(item)
            return enriched
        except BaselineRepositoryError:
            return []

    @staticmethod
    def _source_status(*, candidate_id: str, source_run_id: Any, source_batch_id: Any, approval_state: Any, eligible: Any, approved_source: dict[str, Any] | None) -> tuple[str, str]:
        source_matches = bool(approved_source and approved_source.get("source_candidate_id") == candidate_id)
        if source_matches and approved_source:
            source_matches = all(
                not approved_source.get(key) or approved_source.get(key) == value
                for key, value in (("source_run_id", source_run_id), ("source_batch_id", source_batch_id))
            )
        if source_matches:
            return "APPROVED_SOURCE", "APPROVED SOURCE"
        if eligible is True:
            return "ELIGIBLE_CANDIDATE", "ELIGIBLE CANDIDATE"
        if approval_state == "NOT_ELIGIBLE" or eligible is False:
            return "NOT_ELIGIBLE", "NOT ELIGIBLE"
        if approval_state in {"CANDIDATE", "RUN_ONLY"}:
            return "RUN_ONLY", "RUN ONLY"
        return "UNKNOWN", "UNKNOWN"

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
