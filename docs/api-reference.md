# A11yAdbClient API Reference

`talkback_lib.py`의 `A11yAdbClient`에서 외부 호출을 위해 제공하는 퍼블릭 메서드만 정리한 문서입니다.  
(내부 헬퍼 메서드: `_run`, `_broadcast`, `_extract_*` 등 `_` 접두사 메서드는 제외)

## Table of Contents

- [A11yAdbClient API Reference](#a11yadbclient-api-reference)
  - [생성자](#생성자)
  - [check_helper_status](#check_helper_status)
  - [ping](#ping)
  - [clear_logcat](#clear_logcat)
  - [check_talkback_status](#check_talkback_status)
  - [dump_tree](#dump_tree)
  - [isin](#isin)
  - [select](#select)
  - [touch](#touch)
  - [scroll](#scroll)
  - [move_focus](#move_focus)
  - [get_focus](#get_focus)
  - [reset_focus_history](#reset_focus_history)
  - [move_focus_smart](#move_focus_smart)
  - [scrollFind](#scrollfind)
  - [scrollSelect](#scrollselect)
  - [scrollTouch](#scrolltouch)
  - [typing](#typing)
  - [waitForActivity](#waitforactivity)
  - [get_announcements](#get_announcements)
  - [verify_speech](#verify_speech)

---

## 생성자

### Signature
`A11yAdbClient(adb_path: str = "adb", package_name: str = "com.iotpart.sqe.talkbackhelper", dev_serial: str | None = None, start_monitor: bool = True)`

### 설명
ADB 실행 경로, 헬퍼 앱 패키지명, 기본 디바이스 시리얼 등을 설정하는 클라이언트 생성자입니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `adb_path` | `str` | `"adb"` | 사용할 adb 실행 파일 경로 |
| `package_name` | `str` | `"com.iotpart.sqe.talkbackhelper"` | TalkBack helper 앱 패키지명 |
| `dev_serial` | `str \| None` | `None` | 기본 대상 디바이스 시리얼 |
| `start_monitor` | `bool` | `True` | 내부 모니터링 사용 여부 플래그(현재 인터페이스용 상태값) |

### Returns
- `A11yAdbClient` 인스턴스

### Example
```python
from talkback_lib import A11yAdbClient

client = A11yAdbClient(dev_serial="R3CT12345AB")
```

---

## check_helper_status

### Signature
`check_helper_status(dev: Any = None) -> bool`

### 설명
헬퍼 접근성 서비스 활성화 여부와 명령 수신 준비 상태(`ping`)를 함께 점검합니다.  
실행 전 선행 체크로 사용하면, 테스트 실패 원인(서비스 비활성화)을 빠르게 분리할 수 있습니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | `None` | 디바이스 시리얼 문자열 또는 `serial` 속성을 가진 객체 |

### Returns
- `bool`: 헬퍼 서비스가 활성화되어 있고 `READY` 상태면 `True`, 아니면 `False`

### Example
```python
if not client.check_helper_status(dev_serial):
    raise RuntimeError("접근성 helper 서비스 상태를 확인하세요")
```

---

## ping

### Signature
`ping(dev: Any = None, wait_: float = 3.0) -> bool`

### 설명
헬퍼 앱에 `PING` 브로드캐스트를 보내고 응답 로그를 읽어 readiness를 검증합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | `None` | 대상 디바이스 |
| `wait_` | `float` | `3.0` | 응답 로그 대기 시간(초) |

### Returns
- `bool`: `PING_RESULT.success == True` 이고 `status == "READY"` 이면 `True`

### Example
```python
ready = client.ping(dev_serial, wait_=2.5)
print("helper ready:", ready)
```

---

## clear_logcat

### Signature
`clear_logcat(dev: Any = None) -> str`

### 설명
`adb logcat -c`를 호출해 로그 버퍼를 초기화합니다. 새 명령의 응답 로그만 읽고 싶을 때 유용합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | `None` | 대상 디바이스 |

### Returns
- `str`: 명령 출력 문자열(일반적으로 빈 문자열)

### Example
```python
client.clear_logcat(dev_serial)
```

---

## check_talkback_status

### Signature
`check_talkback_status(dev: Any = None) -> bool`

### 설명
디바이스 설정에서 TalkBack 접근성 서비스 활성화 여부를 확인합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | `None` | 대상 디바이스 |

### Returns
- `bool`: enabled_accessibility_services에 `talkback` 문자열이 있으면 `True`

### Example
```python
if not client.check_talkback_status(dev_serial):
    print("TalkBack이 꺼져 있습니다")
```

---

## dump_tree

### Signature
`dump_tree(dev: Any = None, wait_seconds: float = 5.0) -> list[dict[str, Any]]`

> 응답 포맷 버전: Android Navigator `2.28.0` / Python Client `1.6.7`

### 설명
현재 화면의 접근성 노드 트리를 helper를 통해 덤프합니다.  
`isin`, `scrollFind` 등 탐색/매칭 계열 함수의 기반 데이터입니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | `None` | 대상 디바이스 |
| `wait_seconds` | `float` | `5.0` | 덤프 로그 수집 최대 대기 시간 |

### Returns
- `list[dict[str, Any]]`: 접근성 노드 리스트(`nodes`).
- 추가 메타데이터는 `client.last_dump_metadata`에 저장됩니다.
  - `algorithmVersion`: Android 덤프 알고리즘 버전
  - `canScrollDown`: 현재 화면에서 아래로 더 스크롤 가능한지 여부

### Example
```python
nodes = client.dump_tree(dev_serial)
print("node count:", len(nodes))
```

---

## isin

### Signature
`isin(dev, name: str | list[str], wait_: int = 5, type_: str = "a", index_: int = 0, class_name: str = None, clickable: bool = None, focusable: bool = None) -> bool`

### 설명
현재(또는 대기 시간 내) 화면 접근성 트리에서 대상 요소 존재 여부를 확인합니다.  
텍스트/리소스ID/토크백 발화 기준 검색을 지원하며, TalkBack 자동화에서 “현재 화면에 목표 요소가 있는지”를 판단할 때 사용합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `name` | `str \| list[str]` | 없음 | 검색 패턴(정규식 가능). 리스트+`type_="and"`로 복합 조건 가능 |
| `wait_` | `int` | `5` | 탐색 최대 대기 시간(초) |
| `type_` | `str` | `"a"` | 검색 대상 타입(`a/t/b/r/all/and` 등) |
| `index_` | `int` | `0` | 동일 매칭 다수일 때 인덱스 |
| `class_name` | `str` | `None` | 클래스명 추가 필터 |
| `clickable` | `bool` | `None` | clickable 필터 |
| `focusable` | `bool` | `None` | focusable 필터 |

### Returns
- `bool`: 대상 요소를 찾으면 `True`

### Example
```python
exists = client.isin(dev_serial, "설정", wait_=3, type_="text")
```

---

## select

### Signature
`select(dev, name: str | list[str], wait_: int = 5, type_: str = "a", index_: int = 0, class_name: str = None, clickable: bool = None, focusable: bool = None) -> bool`

### 설명
대상 요소를 찾아 TalkBack 포커스를 이동(선택)합니다.  
실제 클릭 전, “해당 항목을 포커스하여 읽게 만들기” 단계에 적합합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `name` | `str \| list[str]` | 없음 | 타겟 이름/패턴 |
| `wait_` | `int` | `5` | 탐색 최대 대기 시간(초) |
| `type_` | `str` | `"a"` | 타겟 타입 |
| `index_` | `int` | `0` | 매칭 인덱스 |
| `class_name` | `str` | `None` | 클래스명 필터 |
| `clickable` | `bool` | `None` | clickable 필터 |
| `focusable` | `bool` | `None` | focusable 필터 |

### Returns
- `bool`: 포커스 이동 성공 시 `True`

### Example
```python
ok = client.select(dev_serial, "Wi-Fi", type_="text")
```

---

## touch

### Signature
`touch(dev, name: str | list[str], wait_: int = 5, type_: str = "a", index_: int = 0, long_: bool = False, class_name: str = None, clickable: bool = None, focusable: bool = None) -> bool`

### 설명
대상 요소를 찾아 클릭(또는 롱클릭) 액션을 수행합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `name` | `str \| list[str]` | 없음 | 타겟 이름/패턴 |
| `wait_` | `int` | `5` | 탐색 최대 대기 시간(초) |
| `type_` | `str` | `"a"` | 타겟 타입 |
| `index_` | `int` | `0` | 매칭 인덱스 |
| `long_` | `bool` | `False` | 롱클릭 여부 |
| `class_name` | `str` | `None` | 클래스명 필터 |
| `clickable` | `bool` | `None` | clickable 필터 |
| `focusable` | `bool` | `None` | focusable 필터 |

### Returns
- `bool`: 액션 성공 시 `True`

### Example
```python
client.touch(dev_serial, "확인", type_="text")
client.touch(dev_serial, "앱 아이콘", long_=True)
```

---

## scroll

### Signature
`scroll(dev, direction, step_=50, time_=1000, bounds_=None) -> bool`

### 설명
현재 화면에서 스크롤을 수행합니다.  
`direction`은 `up/down/left/right`(또는 `u/d/l/r`)를 지원합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `direction` | `str` | 없음 | 스크롤 방향 |
| `step_` | `int` | `50` | (현재 인터페이스 예약값) |
| `time_` | `int` | `1000` | (현재 인터페이스 예약값) |
| `bounds_` | `Any` | `None` | (현재 인터페이스 예약값) |

### Returns
- `bool`: 스크롤 명령 성공 시 `True`

### Example
```python
client.scroll(dev_serial, "down")
client.scroll(dev_serial, "u")
```

---

## move_focus

### Signature
`move_focus(dev: Any = None, direction: str = "next") -> bool`

### 설명
TalkBack 포커스를 다음(`next`) 또는 이전(`prev`) 요소로 이동합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | `None` | 대상 디바이스 |
| `direction` | `str` | `"next"` | `next` 또는 `prev` |

### Returns
- `bool`: 포커스 이동 성공 시 `True`

### Example
```python
client.move_focus(dev_serial, "next")
client.move_focus(dev_serial, "prev")
```

---


## get_focus

### Signature
`get_focus(dev: Any = None, wait_seconds: float = 2.0) -> dict[str, Any]`

### 설명
`ACTION_GET_FOCUS` 브로드캐스트를 전송하고 `FOCUS_RESULT` 로그를 읽어 현재 TalkBack 포커스 노드 정보를 반환합니다.
`FOCUS_RESULT`가 비어 있거나 의미 있는 필드(`text`, `contentDescription`, `viewIdResourceName`, `boundsInScreen`)가 없는 경우에는 `dump_tree()` fallback을 수행해 현재 포커스 노드를 복구합니다. fallback 탐색 우선순위는 `accessibilityFocused == True` 후 `focused == True`이며, children를 DFS(pre-order)로 재귀 탐색합니다.

### Returns
- `dict[str, Any]`: 포커스 노드 정보. 실패 시 빈 dict.
  - 주요 필드: `schemaVersion(1.2.0)`, `snapshotBuilderVersion(1.2.0)`, `text`, `contentDescription`, `mergedLabel`, `talkbackLabel`, `viewIdResourceName`, `className`, `boundsInScreen`, `clickable`, `focusable`, `accessibilityFocused`, `visibleToUser`, `children`.
  - `mergedLabel`은 포커스 노드의 `text/contentDescription`이 비어 있으면 자식 노드 DFS 결과(중복 제거)를 병합해 채웁니다.

---

## reset_focus_history

### Signature
`reset_focus_history(dev: Any = None) -> None`

### 설명
안드로이드 헬퍼 앱의 탐색 히스토리 인덱스를 명시적으로 초기화합니다.  
`dev`에는 문자열 시리얼 또는 `dev.serial`/`dev.device_id`를 가진 객체를 전달할 수 있습니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | `None` | 대상 디바이스. 문자열 serial 또는 디바이스 객체 |

### Returns
- `None`

### Example
```python
client.click_element(dev, targetName="Devices", targetType="b")
client.reset_focus_history(dev)
client.perform_focus(dev, targetName="Location QR code", targetType="b")
client.move_focus_smart(dev)
```

---

## move_focus_smart

### Signature
`move_focus_smart(dev: Any = None, direction: str = "next") -> str`

### 설명
파이썬에서는 무거운 트리 분석(`dump_tree`, `get_focus`)을 수행하지 않고, `ACTION_SMART_NEXT` 브로드캐스트만 전송합니다.
안드로이드 헬퍼가 Smart Next를 실행한 뒤 `SMART_NAV_RESULT` 로그를 반환하며, 클라이언트는 `_read_log_result(..., wait_seconds=3.0)`로 응답을 판독해 상태 문자열을 그대로 반환합니다.
클래스 외부 코드에서는 `client.move_focus_smart(dev)`를 표준 호출로 사용하세요.
또한 `move_focus_smart`는 기존 로그 분석 연속성을 위해 내부에서 `logcat -c`를 호출하지 않습니다.

### Returns
- `"moved"`: 일반 next 이동 성공
- `"scrolled"`: 시스템 내비게이션 바 진입 전 스크롤 후 첫 항목 포커스 성공
- `"looped"`: 마지막 노드에서 첫 항목으로 순환 성공
- `"failed"`: 위 과정 실패

---

## scrollFind

### Signature
`scrollFind(dev, name, wait_=30, direction_='updown', type_='all')`

### 설명
스크롤하면서 대상 요소가 화면에 나타나는지 탐색합니다.  
`updown`/`downup` 옵션으로 한 방향 탐색 실패 시 반대 방향으로 한 번 전환합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `name` | `str \| list[str]` | 없음 | 찾을 타겟 패턴 |
| `wait_` | `int` | `30` | 최대 탐색 시간(초) |
| `direction_` | `str` | `"updown"` | 초기/전환 방향 전략 |
| `type_` | `str` | `"all"` | 검색 타입 |

### Returns
- `True`: 요소 발견
- `False`: 사전 상태 체크 실패
- `None`: 시간 초과 또는 탐색 실패

### Example
```python
found = client.scrollFind(dev_serial, "Pet.*", direction_="down")
if found is True:
    print("찾음")
```

---

## scrollSelect

### Signature
`scrollSelect(dev, name: str | list[str], wait_: int = 60, direction_: str = "updown", type_: str = "a", index_: int = 0, class_name: str = None, clickable: bool = None, focusable: bool = None) -> bool`

### 설명
`scrollFind`로 대상을 찾은 뒤 `select`까지 한 번에 수행하는 편의 함수입니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `name` | `str \| list[str]` | 없음 | 타겟 패턴 |
| `wait_` | `int` | `60` | 탐색 최대 시간 |
| `direction_` | `str` | `"updown"` | 스크롤 방향 전략 |
| `type_` | `str` | `"a"` | 검색 타입 |
| `index_` | `int` | `0` | 매칭 인덱스 |
| `class_name` | `str` | `None` | 클래스명 필터 |
| `clickable` | `bool` | `None` | clickable 필터 |
| `focusable` | `bool` | `None` | focusable 필터 |

### Returns
- `bool`: 최종 `select` 성공 여부

### Example
```python
ok = client.scrollSelect(dev_serial, "블루투스", direction_="updown", type_="text")
```

---

## scrollTouch

### Signature
`scrollTouch(dev, name: str | list[str], wait_: int = 60, direction_: str = "updown", type_: str = "a", index_: int = 0, long_: bool = False, class_name: str = None, clickable: bool = None, focusable: bool = None) -> bool`

### 설명
`scrollFind`로 대상을 찾은 뒤 `touch`까지 한 번에 수행하는 편의 함수입니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `name` | `str \| list[str]` | 없음 | 타겟 패턴 |
| `wait_` | `int` | `60` | 탐색 최대 시간 |
| `direction_` | `str` | `"updown"` | 스크롤 방향 전략 |
| `type_` | `str` | `"a"` | 검색 타입 |
| `index_` | `int` | `0` | 매칭 인덱스 |
| `long_` | `bool` | `False` | 롱클릭 여부 |
| `class_name` | `str` | `None` | 클래스명 필터 |
| `clickable` | `bool` | `None` | clickable 필터 |
| `focusable` | `bool` | `None` | focusable 필터 |

### Returns
- `bool`: 최종 `touch` 성공 여부

### Example
```python
ok = client.scrollTouch(dev_serial, "개인정보", type_="text")
```

---

## typing

### Signature
`typing(dev, name: str, adbTyping=False)`

### 설명
현재 포커스된 입력 요소에 텍스트를 입력합니다.  
- `adbTyping=True`: `adb shell input text` 직접 입력
- 기본값(`False`): helper 브로드캐스트 기반 입력

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `name` | `str` | 없음 | 입력할 문자열 |
| `adbTyping` | `bool` | `False` | adb 직접 입력 사용 여부 |

### Returns
- 성공 시 `None`
- 실패 시 `False`

### Example
```python
client.typing(dev_serial, "hello world")
client.typing(dev_serial, "raw_input", adbTyping=True)
```

---

## waitForActivity

### Signature
`waitForActivity(dev, ActivityName: str, waitTime: int) -> bool`

### 설명
`dumpsys window windows`를 반복 조회하여 특정 액티비티 전환 완료를 대기합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `ActivityName` | `str` | 없음 | 기대 액티비티 이름(부분 문자열 매칭) |
| `waitTime` | `int` | 없음 | 최대 대기 시간(ms) |

### Returns
- `bool`: 조건 만족 시 `True`

### Example
```python
ok = client.waitForActivity(dev_serial, "SettingsActivity", 5000)
```

---

## get_announcements

### Signature
`get_announcements(dev: Any = None, wait_seconds: float = 2.0, only_new: bool = True) -> list[str]`

### 설명
로그캣의 `A11Y_ANNOUNCEMENT` 태그를 수집해 TalkBack 발화 문자열 목록을 반환합니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | `None` | 대상 디바이스 |
| `wait_seconds` | `float` | `2.0` | 발화 수집 대기 시간 |
| `only_new` | `bool` | `True` | 이전 읽기 이후 신규 로그만 수집할지 여부 |

### Returns
- `list[str]`: 수집된 발화 문장 목록(시간순)

### Example
```python
ann = client.get_announcements(dev_serial, wait_seconds=1.5)
print(ann[-1] if ann else "발화 없음")
```

---

## verify_speech

### Signature
`verify_speech(dev, expected_regex: str, wait_seconds: float = 3.0, take_error_snapshot: bool = True) -> bool`

### 설명
대상 화면을 캡처한 뒤 TalkBack 발화를 수집하고, 기대 정규식과 비교해 검증합니다.  
실패 시(옵션 활성화 시) `error_log/`에 EXPECTED/ACTUAL 오버레이 이미지를 남겨 디버깅을 돕습니다.

### Parameters

| 이름 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `dev` | `Any` | 없음 | 대상 디바이스 |
| `expected_regex` | `str` | 없음 | 기대 발화 정규식 |
| `wait_seconds` | `float` | `3.0` | 발화 수집 대기 시간 |
| `take_error_snapshot` | `bool` | `True` | 실패 시 스냅샷 저장 여부 |

### Returns
- `bool`: 정규식 매칭 성공 시 `True`, 실패 시 `False`

### Example
```python
client.select(dev_serial, "Pet.*")
ok = client.verify_speech(dev_serial, expected_regex="Pet.*")
print("PASS" if ok else "FAIL")
```

---

## 빠른 사용 패턴 예시

```python
from talkback_lib import A11yAdbClient

client = A11yAdbClient()
dev = "R3CT12345AB"

if client.check_helper_status(dev):
    if client.scrollSelect(dev, "Wi-Fi", type_="text"):
        speech_ok = client.verify_speech(dev, r"Wi[- ]?Fi")
        print("speech check:", speech_ok)
```
