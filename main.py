from test_a11y import A11yAdbClient
import time

def run_integration_test():
    # 1. 클라이언트 초기화 (adb 경로 및 패키지명 확인)
    client = A11yAdbClient()
    
    # 단말기 지정 (여러 대인 경우 시리얼 번호 입력)
    dev_serial = "R3CX40QFDBP" 
    
    try:
        print("=== TalkBack 자동화 통합 테스트 시작 ===")
        
        # 2. 존재 여부 확인 (isin) 테스트
        # 레거시 호환: name, wait_, type_, index_ 사용
        exists = client.isin(dev_serial, name="라이프", wait_=5, type_='a')
        print(f"[isin] '라이프' 객체 존재 여부: {exists}")
        
        if exists:
            # 3. 터치 (touch) 테스트
            # 레거시 호환: name, wait_, type_, index_, long_ 사용
            success = client.touch(dev_serial, name="라이프", wait_=5, type_='a', index_=0)
            print(f"[touch] '라이프' 클릭 결과: {success}")
            
            # 4. 음성 안내 결과 확인
            # 이전 액션(touch) 후의 안내 메시지들 출력
            announcements = client.get_announcements(dev=dev_serial, wait_seconds=2.0)
            print(f"[Announcements] 수집된 음성: {announcements}")
            
    except Exception as e:
        print(f"오류 발생: {e}")
    finally:
        # 5. 모니터링 스레드 및 자원 정리
        # 리팩토링된 코드에 포함된 종료 로직 호출
        print("자원 정리 중...")

if __name__ == "__main__":
    run_integration_test()
