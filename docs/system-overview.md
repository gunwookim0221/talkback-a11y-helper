# System Overview

## Overview

이 시스템은 Android 단말 내부의 헬퍼 앱만이 아니라, PC/CI 자동화 환경까지 포함한 **종단 간 접근성 자동화 아키텍처**입니다. 핵심 목표는 TalkBack 탐색 결과를 안정적으로 수집하고, 이를 검증 가능한 구조화 데이터(JSON)로 반환하는 것입니다.

## End-to-End Flow

```text
PC Automation Script
    -> ADB broadcast
    -> Helper App
    -> Accessibility Tree
    -> Target App UI
```

## Automation Communication Flow

다음은 Python 스크립트 또는 CI 잡에서 실제로 수행되는 일반 흐름입니다.

1. Automation Script (Python/CI)가 테스트 시나리오를 실행합니다.
2. `adb broadcast` 명령으로 헬퍼 앱에 제어 신호를 전송합니다.
3. 헬퍼 앱이 명령을 수신하고 접근성 트리를 탐색합니다.
4. 현재 포커스 노드 정보를 수집/정규화합니다.
5. 결과를 JSON 형태로 반환(또는 저장/출력)합니다.

## Why a Helper App Is Required

TalkBack 자동화에는 일반 입력 자동화만으로 해결되지 않는 제약이 있습니다.

- `adb swipe`는 TalkBack navigation을 재현하지 못합니다.
- DPAD/TAB navigation은 TalkBack 읽기 순서와 다를 수 있습니다.
- 일부 기기에서는 TTS 로그가 암호화되어 logcat만으로 실제 발화를 확인하기 어렵습니다.

따라서 헬퍼 앱은 접근성 이벤트/노드 중심의 인터페이스를 제공하여, 기기별 편차가 큰 환경에서도 비교적 일관된 자동화 신호를 제공합니다.

## Stability Characteristics

이 아키텍처는 다음 특성으로 인해 접근성 QA 자동화에 유리합니다.

- 좌표 입력이 아닌 접근성 상태 중심 검증
- 스크립트-디바이스 간 명령 채널 표준화(ADB broadcast)
- 포커스/역할/상태 정보를 구조화된 JSON으로 전달

## Known Limitations

- Samsung 기기에서는 TTS 로그가 인코딩/암호화될 수 있습니다.
- speech overlay가 UIAutomator XML dump에서 관찰되지 않을 수 있습니다.
- `RecyclerView` / `WebView` / Compose UI에서 traversal 순서가 달라질 수 있습니다.

## Future Improvements

- 공간 기반 navigation 알고리즘 고도화
- container-aware traversal 도입
- locale 기반 speech prediction 확장
- OCR 기반 검증 정확도 향상
