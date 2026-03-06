# Testing Pipeline

[System Overview 보기](system-overview.md) | [Architecture 보기](architecture.md)

## Overview

이 문서는 TalkBack 기반 접근성 QA 자동화 검증 파이프라인을 단계별로 설명합니다. 핵심은 헬퍼 앱을 통해 현재 접근성 포커스를 수집하고, 예상 발화와 실제 발화를 비교해 PASS/FAIL을 판단하는 것입니다.

## Step 1 – TalkBack 활성화

- 테스트 단말에서 TalkBack을 활성화합니다.
- 필요 시 개발자 옵션과 접근성 설정을 사전 구성합니다.

## Step 2 – 접근성 포커스 이동

헬퍼 앱에 다음/이전 탐색 명령을 전달하여 TalkBack 유사 포커스 이동을 수행합니다.

예시 명령:

```bash
adb shell am broadcast -a com.example.a11yhelper.NEXT
```

## Step 3 – 현재 포커스 노드 정보 수집

이동 후 현재 포커스 노드 정보를 요청합니다.

예시 명령:

```bash
adb shell am broadcast -a com.example.a11yhelper.GET_FOCUS
```

헬퍼 앱은 포커스 노드 메타데이터(`text`, `className`, `checked`, `selected` 등)를 JSON 형태로 반환/저장/출력합니다.

## Step 4 – 예상 TalkBack 발화 생성

일반적으로 TalkBack 발화는 다음 요소의 조합으로 모델링할 수 있습니다.

- `text`
- `role` (`className` 기반)
- `state` (`checked`, `selected` 등)

예시:

- `Settings` + `Button` -> `"Settings button"`

## Step 5 – TalkBack speech overlay 캡처

Android 개발자 옵션의 **Display speech output** 기능을 활용하면 TalkBack 발화가 화면 하단 오버레이로 표시됩니다.

다음 명령으로 화면 캡처를 수행할 수 있습니다.

```bash
adb exec-out screencap
```

캡처 이미지에서 OCR을 사용해 overlay 텍스트를 추출할 수 있습니다.

## Step 6 – 예상 발화와 실제 발화 비교

- Expected Utterance(예상 발화)와 OCR 추출 결과(실제 발화)를 비교합니다.
- 일치/유사도 기준에 따라 PASS 또는 FAIL을 판정합니다.

## 제한 사항 및 향후 개선

제한 사항 및 향후 개선 방향은 [System Overview](system-overview.md#known-limitations) 문서를 참고하세요.


---

다른 문서 보기: [System Overview](system-overview.md) | [Architecture](architecture.md)
