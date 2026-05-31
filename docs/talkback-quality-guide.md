# TalkBack Quality Classification

이 문서는 QA Frontend에서 수행된 테스트 결과의 접근성 품질(TalkBack Quality)을 판정하는 기준을 설명합니다.

## 현재 운영 기준

### FAIL
실제 접근성 품질 문제로 판정되어 즉각적인 수정이 필요한 케이스입니다.
- **예시**:
  - `TEXT_MISMATCH`
  - `LABEL_MISMATCH`
  - `SPOKEN_MISMATCH`
  - `EMPTY_SPEECH` (UI가 존재하나 발화 내용이 없음)

### ISSUE
접근성 검증이 불가능한 상태이거나 심각한 런타임 오류가 발생한 케이스입니다.
- **예시**:
  - `EMPTY_VISIBLE` (화면에 대상 UI가 보이지 않음)
  - 치명적인 플러그인 에러나 탐색 불가 예외 (아래 Runtime Warning 정책 참조)

### REVIEW
결함은 아니나 기획 의도와 완벽히 일치하지 않아 사람의 판단이 필요한 참고 케이스입니다.
- **예시**:
  - `PARTIAL_MATCH`
  - `REPRESENTATIVE_CONTEXT`
  - 발화와 화면 표시가 같음에도 이동(move_failed) 문제가 일어났던 경우 등

### CLEAN
완전히 정상으로 동작하고 판정된 케이스입니다.
- **예시**:
  - `EXACT_MATCH`
  - 예외 처리된 정상 종료 경고(terminal_reached 등)

---

# Scenario Quality

Scenario 상태 산정 규칙은 해당 시나리오 내에서 발생한 가장 심각한 문제 레벨에 따라 전체 상태를 결정합니다.
1. 하나라도 **FAIL** 발생 시 -> `FAIL`
2. 하나라도 **ISSUE** 발생 시 -> `ISSUE`
3. 하나라도 **REVIEW** 발생 시 -> `REVIEW`
4. 위 문제가 없는 경우 -> `CLEAN`

---

# Quality Signals

시나리오별 구체적인 불일치 혹은 경고 신호를 나열합니다.

### 기본 표시 대상
실제 액션이 필요한 최우선 검토 대상들만 기본적으로 노출됩니다.
- **FAIL**
- **ISSUE**

### Review Signals (접힘 영역)
결함 가능성이 낮은 항목은 UI 공간을 차지하지 않도록 숨김(details) 처리됩니다.
- `PARTIAL_MATCH`
- `REPRESENTATIVE_CONTEXT`
- 그 외 `REVIEW` 카테고리로 분류된 모든 신호

---

# Runtime Warning 정책

테스트 중 발생하는 런타임 경고(`failure_reason`) 중 일부는 정상적인 탐색 종료로 간주하여 무시하고, 치명적인 문제만 예외로 취급합니다.

### 무시 (정상 분류)
- `repeat_no_progress`
- `viewport_exhausted`
- `terminal_reached`
- `end_of_content`
- `no_unvisited_local_tab`

### 실제 문제 (ISSUE 분류)
- `plugin_open_failed`
- `terminal_not_handled`
- `activation_fail`
- `parse_error`
- `exception`
- `fatal`
