from __future__ import annotations

import sys
from talkback_lib import A11yAdbClient


def main() -> None:
    client = A11yAdbClient()

    # 1. 연결된 모든 장치 리스트 가져오기
    try:
        devices = client._run(["devices"]).strip().split('\n')[1:]
        devices = [line.split('\t')[0] for line in devices if '\tdevice' in line]
    except Exception as e:
        print(f"[ERROR] 단말기 목록을 가져오는 중 오류 발생: {e}")
        return

    # 2. 연결된 단말기가 없는 경우 처리
    if not devices:
        print("[ERROR] 연결된 안드로이드 단말기가 없습니다. USB 연결을 확인해 주세요.")
        return

    # 3. 첫 번째 단말기([0])를 자동으로 할당
    dev_serial = devices[0]
    print(f"[*] 연결된 단말기 감지: {dev_serial}")

    target_name = "Pet.*" # 또는 "(?i)Pet.*"

    # 헬퍼 앱 서비스 상태 체크
    if not client.check_helper_status(dev_serial):
        print("[GUIDE] 헬퍼 앱 접근성 서비스 활성화 후 다시 실행해 주세요.")
        sys.exit(1)

    print(f"=== TalkBack 발화 검증 테스트 시작 (Target: {target_name}) ===")

    # 스크롤 탐색 시작
    found = client.scrollFind(dev_serial, target_name, direction_="down")
    if not found:
        print(f"[FAIL] 스크롤 탐색 실패: {target_name}")
        return

    # 발화 검증 실행
    client.select(dev_serial, target_name)
    result = client.verify_speech(dev_serial, expected_regex=target_name)
    if result:
        print(f"[PASS] 발화 검증 성공: {target_name}")
    else:
        print(f"[FAIL] 발화 검증 실패: {target_name} (error_log 폴더 확인)")

if __name__ == "__main__":
    main()
