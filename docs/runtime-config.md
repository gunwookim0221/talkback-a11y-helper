# Runtime Config Guide

이 문서는 `config/runtime_config.json` 운영 원칙을 요약한다.

## 1) 병합 구조

최종 runtime 값은 대략 아래 순서로 합쳐진다.

1. 코드 기본값
2. runtime `defaults`
3. base scenario
4. scenario group
5. shared ref
6. runtime `scenarios.<id>` override

## 2) 주요 운영 포인트

- `enabled=false`면 scenario skip
- `max_steps`는 main step 상한
- scenario별 임시 실험은 runtime override로 수행
- base scenario 정의는 `tb_runner/scenario_config.py`
- 실행 on/off는 `config/runtime_config.json`에서 제어

## 3) Devices plugin 운영 원칙

- `device_*_plugin`은 기본 runtime에서 `enabled=false` 유지
- smoke / long-run 시에는 메모리 override 또는 임시 runtime override 사용
- 장기 검증은 보통 `max_steps=40` override로 수행
- 기본 파일은 보수적으로 유지한다

## 4) override 팁

- representative smoke: `max_steps=5`
- long-run regression: `max_steps=40`
- 전체 기본값을 건드리기보다 scenario별 override를 우선한다

## 5) 주의점

- 새 scenario를 base config에 추가해도 runtime에서 켜지지 않으면 실행되지 않는다
- Devices plugin 전체 추가가 끝난 상태여도 runtime 기본값은 비활성 유지가 운영 기준이다

## 6) V8 Runtime Probe 활성화

V8 Runtime Probe는 `config/runtime_config.json`의 일반 scenario enablement와 별도다.

현재 활성화 경로:

- 환경변수 `TB_V8_COVERAGE_PROBE=1`
- `tb_runner/run_spec.py`의 `enable_coverage_probe=True`
- QA Frontend Run panel의 V8 Runtime Probe toggle

중요한 점:

- `runtime_config.json`은 probe on/off의 primary source가 아니다.
- probe는 run subprocess env로 전달되는 opt-in feature다.
- scenario 자체가 runtime에서 disabled면 probe도 실행되지 않는다.

현재 probe가 켜지면 scenario별 artifact가 추가로 생성된다.

- `*.coverage_probe_plan.json`
- `*.coverage_probe_results.json`
- `*.coverage_probe_results.aggregate.json`
- `*.coverage_probe_validation.json`
- `*.coverage_probe_validation.aggregate.json`
