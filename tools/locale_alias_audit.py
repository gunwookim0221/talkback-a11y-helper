from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

AUDIT_TARGETS = (
    "tb_runner/scenario_config.py",
    "tb_runner/collection_flow.py",
    "app/src/main/java/com/iotpart/sqe/talkbackhelper/A11yHelperService.kt",
)

TOKEN_ALIASES = {
    "navigate up": ("위로 이동", "상위 메뉴로 이동"),
    "more options": ("더보기",),
    "smartthings settings": ("스마트싱스 설정",),
    "location qr code": ("장소 QR 코드", "장소 qr 코드"),
    "change location": ("장소 변경",),
    "no history": ("기록 없음", "내역 없음", "사용 기록 없음"),
    "no activity": ("활동 없음",),
    "no data": ("데이터 없음",),
    "no events": ("이벤트 없음",),
    "nothing yet": ("아직 없음",),
    "set up now": ("지금 설정하기",),
    "set up": ("설정하기", "설정"),
    "later": ("나중에",),
    "continue": ("계속",),
    "next": ("다음",),
    "skip": ("건너뛰기",),
    "open": ("열기",),
}


def _line_has_alias(line: str, aliases: tuple[str, ...]) -> bool:
    lowered = line.casefold()
    return any(alias.casefold() in lowered for alias in aliases)


def audit_locale_aliases() -> list[str]:
    findings: list[str] = []
    for relative in AUDIT_TARGETS:
        path = ROOT / relative
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            lowered = line.casefold()
            for token, aliases in TOKEN_ALIASES.items():
                if token not in lowered:
                    continue
                if _line_has_alias(line, aliases):
                    continue
                findings.append(f"{relative}:{lineno}: token='{token}' missing_inline_alias='{aliases[0]}'")
    return findings


def main() -> int:
    findings = audit_locale_aliases()
    for finding in findings:
        print(finding)
    print(f"locale_alias_audit findings={len(findings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
