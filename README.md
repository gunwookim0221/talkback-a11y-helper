# TalkBack A11y Helper (`com.example.a11yhelper`)

ADB 기반 자동화에서 접근성 서비스로 **현재 화면 트리를 덤프하고**,
원하는 노드에 대해 **직접 포커스/클릭 액션**을 수행하기 위한 debug용 헬퍼 APK입니다.

## 프로젝트 구성

- `A11yHelperService`
  - 이벤트 수신: `TYPE_VIEW_ACCESSIBILITY_FOCUSED`, `TYPE_VIEW_FOCUSED`, `TYPE_WINDOW_STATE_CHANGED`, `TYPE_ANNOUNCEMENT`
  - `TYPE_WINDOW_STATE_CHANGED` 발생 시 `SCREEN_CHANGED` 로그 출력
  - 현재 포커스 노드 스냅샷 JSON 생성/갱신
  - 루트 트리 전체 덤프 및 타겟 액션(포커스/클릭) 수행
- `A11yCommandReceiver`
  - 브로드캐스트 액션 처리
    - `com.example.a11yhelper.GET_FOCUS`
    - `com.example.a11yhelper.DUMP_TREE`
    - `com.example.a11yhelper.FOCUS_TARGET`
    - `com.example.a11yhelper.CLICK_TARGET`
- `A11yNavigator`
  - 화면 트리 DFS 순회
  - Flat JSON 배열 덤프 생성
  - `targetText` 또는 `targetViewId`로 노드 매칭 후 액션 수행
- `A11yStateStore`
  - 메모리 `lastFocusJson` 유지
  - 필요 시 `/sdcard/a11y_focus.json` 저장 시도

## 빌드 / 설치

```bash
./gradlew assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

## ADB 사용 예시

### 1) 현재 포커스 JSON 요청

```bash
adb shell am broadcast -a com.example.a11yhelper.GET_FOCUS --ez saveFile true
```

### 2) 전체 화면 트리 덤프

```bash
adb shell am broadcast -a com.example.a11yhelper.DUMP_TREE
```

- logcat: `A11Y_HELPER DUMP_TREE_RESULT [...]`
- 각 노드 필드: `text`, `contentDescription`, `className`, `viewIdResourceName`, `boundsInScreen`, `clickable`, `focusable`, `isVisibleToUser`

### 3) 특정 타겟 접근성 포커스

```bash
adb shell am broadcast -a com.example.a11yhelper.FOCUS_TARGET --es targetText "확인"
adb shell am broadcast -a com.example.a11yhelper.FOCUS_TARGET --es targetViewId "com.example.app:id/btn_ok"
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {...}`

### 4) 특정 타겟 클릭

```bash
adb shell am broadcast -a com.example.a11yhelper.CLICK_TARGET --es targetText "확인"
adb shell am broadcast -a com.example.a11yhelper.CLICK_TARGET --es targetViewId "com.example.app:id/btn_ok"
```

- logcat: `A11Y_HELPER TARGET_ACTION_RESULT {...}`

### 5) 로그 확인

```bash
adb logcat -d | grep A11Y_HELPER
```
