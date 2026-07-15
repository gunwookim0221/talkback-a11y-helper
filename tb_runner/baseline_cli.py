"""Non-interactive command interface for the Phase 10.2 baseline repository."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tb_runner.baseline_artifact_store import sha256_file
from tb_runner.baseline_repository import (
    ApprovalRequest,
    ArtifactPinPolicy,
    BaselineRepository,
    BaselineRepositoryError,
)
from tb_runner.baseline_repository_validator import offline_revalidate_candidate


def _json_file(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise BaselineRepositoryError("limitation snapshot must be a JSON array of objects")
    return value


def _actor(args: argparse.Namespace) -> dict[str, str]:
    return {"identity": args.actor, "authentication_source": args.auth_source}


def _write_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--auth-source", required=True)
    parser.add_argument("--reason", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tb_runner.baseline_cli")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_candidate = commands.add_parser("inspect-candidate")
    inspect_candidate.add_argument("candidate")
    validate_candidate = commands.add_parser("validate-candidate")
    validate_candidate.add_argument("candidate")
    validate_candidate.add_argument("--digest")

    approve = commands.add_parser("approve")
    _write_args(approve)
    approve.add_argument("candidate")
    approve.add_argument("--digest", required=True)
    approve.add_argument("--acceptance", choices=("PASS", "PASS WITH LIMITATIONS"), required=True)
    approve.add_argument("--limitations-json")
    approve.add_argument("--known-limitations-json")
    approve.add_argument("--accept-limitations", action="store_true")
    approve.add_argument("--supersedes")
    approve.add_argument("--pin-optional", action="append", default=[])

    reject = commands.add_parser("reject")
    _write_args(reject)
    reject.add_argument("candidate")
    reject.add_argument("--digest")
    reject.add_argument("--category", required=True)

    supersede = commands.add_parser("supersede")
    _write_args(supersede)
    supersede.add_argument("baseline_id")
    supersede.add_argument("--by", required=True)

    archive = commands.add_parser("archive")
    _write_args(archive)
    archive.add_argument("identifier")

    listing = commands.add_parser("list-baselines")
    listing.add_argument("--repository", required=True)
    listing.add_argument("--active-only", action="store_true")
    inspect_baseline = commands.add_parser("inspect-baseline")
    inspect_baseline.add_argument("--repository", required=True)
    inspect_baseline.add_argument("baseline_id")
    verify = commands.add_parser("verify-repository")
    verify.add_argument("--repository", required=True)
    rebuild = commands.add_parser("rebuild-index")
    rebuild.add_argument("--repository", required=True)
    return parser


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect-candidate":
            path = Path(args.candidate)
            payload = json.loads(path.read_text(encoding="utf-8"))
            _emit({"candidate": payload, "document_digest": sha256_file(path)})
            return 0
        if args.command == "validate-candidate":
            result = offline_revalidate_candidate(args.candidate, expected_candidate_digest=args.digest)
            _emit(
                {
                    "valid": result.valid,
                    "candidate_id": result.candidate.get("candidate_id"),
                    "candidate_digest": result.candidate_digest,
                    "checks": result.checks,
                }
            )
            return 0 if result.valid else 1

        repository = BaselineRepository(args.repository)
        if args.command == "approve":
            result = repository.approve(
                ApprovalRequest(
                    candidate_path=Path(args.candidate),
                    candidate_digest=args.digest,
                    reviewer=_actor(args),
                    reason=args.reason,
                    acceptance_result=args.acceptance,
                    structured_limitations=tuple(_json_file(args.limitations_json)),
                    known_limitation_snapshot=tuple(_json_file(args.known_limitations_json)),
                    limitations_explicitly_accepted=args.accept_limitations,
                    supersedes=args.supersedes,
                    artifact_pin_policy=ArtifactPinPolicy(optional_artifact_types=tuple(args.pin_optional)),
                )
            )
            _emit(
                {
                    "baseline_id": result.baseline_id,
                    "baseline_key_digest": result.baseline_key_digest,
                    "package_path": result.package_path,
                    "core_checksums": result.core_checksums,
                    "warnings": result.warnings,
                }
            )
        elif args.command == "reject":
            _emit(
                repository.reject(
                    args.candidate,
                    reviewer=_actor(args),
                    reason=args.reason,
                    category=args.category,
                    candidate_digest=args.digest,
                )
            )
        elif args.command == "supersede":
            _emit(
                repository.supersede(
                    args.baseline_id,
                    superseded_by=args.by,
                    actor=_actor(args),
                    reason=args.reason,
                )
            )
        elif args.command == "archive":
            _emit(repository.archive(args.identifier, actor=_actor(args), reason=args.reason))
        elif args.command == "list-baselines":
            _emit(repository.list_baselines(include_inactive=not args.active_only))
        elif args.command == "inspect-baseline":
            _emit(repository.inspect_baseline(args.baseline_id))
        elif args.command == "verify-repository":
            result = repository.verify()
            _emit(result.__dict__)
            return 0 if result.valid else 1
        elif args.command == "rebuild-index":
            _emit(repository.rebuild_indexes())
        return 0
    except (BaselineRepositoryError, OSError, ValueError, json.JSONDecodeError) as exc:
        _emit({"error": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["build_parser", "main"]
