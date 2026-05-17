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
