# TalkBack Quality Classification

이 문서는 QA Frontend에서 제공하는 TalkBack 접근성 자동화 품질의 세부 판정 기준 및 시그널 의미를 정의합니다.

---

## FAIL
실제 접근성 품질 문제로 판정되어 즉각적인 수정이 필요한 케이스입니다. 화면과 발화 간의 내용 불일치 혹은 심각한 접근성 결함이 여기에 해당합니다.
- **예**:
  - `TEXT_MISMATCH`
  - `LABEL_MISMATCH`
  - `SPOKEN_MISMATCH`
  - `EMPTY_SPEECH` (UI는 존재하지만 TalkBack 발화 내용이 비어있음)

## ISSUE
정상적인 접근성 검증이 불가능한 상태이거나 자동화 탐색을 방해하는 심각한 런타임 오류 케이스입니다.
- **예**:
  - `EMPTY_VISIBLE` (발화 대상 UI를 화면에서 찾을 수 없음)
  - 치명적인 플러그인 에러나 탐색 예외 발생 (아래 Runtime Warning 정책 참조)

## REVIEW
명백한 결함은 아니나, 텍스트가 일부만 일치하거나 기획 의도와 다를 수 있어 사람의 판단 및 검토가 필요한 케이스입니다.
- **예**:
  - `PARTIAL_MATCH`
  - `REPRESENTATIVE_CONTEXT`
  - (발화와 표시가 같더라도 특정 보조 신호 문제가 발생하여 확인이 필요한 경우)

## CLEAN
어떠한 결함이나 모호성 없이 완벽하게 정상 동작한 케이스입니다.
- **예**:
  - `EXACT_MATCH`
  - 예외 처리된 정상 종료 상태

---

# Scenario Quality

개별 시나리오의 최종 품질 상태는 내부 스텝들 중 **가장 심각한 문제 레벨**을 기준으로 산정됩니다. 판정 우선순위는 다음과 같습니다:

1. **FAIL**: 내부 스텝 중 하나라도 FAIL 판정을 받은 경우
2. **ISSUE**: FAIL이 없고, 하나라도 ISSUE 판정을 받은 경우
3. **REVIEW**: FAIL/ISSUE가 없고, 하나라도 REVIEW 판정을 받은 경우
4. **CLEAN**: 모든 스텝에 문제가 없을 경우

---

# Quality Signals

스텝 단위의 세부 불일치 원인을 시그널 리스트로 보여줍니다.

## 기본 표시
조치가 필요한 중요 시그널들은 화면에 기본적으로 노출됩니다.
- **FAIL**
- **ISSUE**

## Review Signals (접힘 영역)
단순 참고용인 REVIEW 항목들은 UI 공간을 차지하지 않도록 `<details>` 접힘 영역 내부에 숨김 처리됩니다.
- **예**: `PARTIAL_MATCH`, `REPRESENTATIVE_CONTEXT`

---

# Runtime Warning 정책

테스트 런타임 중 보고되는 `failure_reason` 값들에 대한 처리 기준입니다.

## 무시
자동화 탐색 로직 상 발생하는 자연스러운 종료 상황으로 간주하여 `CLEAN` 또는 현재의 기본 상태를 유지합니다.
- `repeat_no_progress`
- `viewport_exhausted`
- `terminal_reached`
- `end_of_content`
- `no_unvisited_local_tab`

## 실제 문제
자동화 도구의 진행을 방해하거나 치명적인 예외가 발생한 상황으로, 발생 시 해당 시나리오를 `ISSUE`로 격상시킵니다.
- `plugin_open_failed`
- `terminal_not_handled`
- `activation_fail`
- `parse_error`
- `exception`
