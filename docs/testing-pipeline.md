# Testing Pipeline (현재 운영 기준)

[System Overview](system-overview.md) | [Runner Flow](runner_flow.md) | [Device Plugin Guide](device-plugin-guide.md)

## 1) 실행 진입

- entrypoint: `script_test.py`
- runtime bundle 로드
- enabled scenario 순차 실행
- checkpoint / final Excel 저장

## 2) 대표 검증 층위

### Representative smoke

- Global
- representative Life plugins
- representative Device plugins

### Expanded smoke

- 남은 Life / Device plugin 추가

### Long-run regression

- Global group
- Life group
- Device group
- 보통 `max_steps=40` 기준

## 3) Devices plugin 검증 포인트

- `All devices` selected 보장
- filter drift 없음
- visible inventory match
- safe tap 정상
- `plugin_open_verified`
- Devices card search에는 **ADB swipe** 사용

## 4) Locale 검증 포인트

- ko-KR
- English SmartThings UI
- mixed-language device base label 허용
- state suffix는 normalize에서 제거

예:

- `연기 Clear -> 연기`
- `누수 Dry -> 누수`
- `Audio Pause -> Audio`
- `Camera Connected -> Camera`

## 5) Report row 검증 포인트

- `visible_label`은 actual TalkBack focus
- crop과 visible이 일치해야 함
- representative는 `representative_*`로 별도 보존

## 6) 현재 운영 baseline

- Global long-run: `7/7` pass
- Life long-run: `12/12` pass
- Device long-run: `12/12` 실질 pass
- fatal / traceback 없음
- Excel save 성공
