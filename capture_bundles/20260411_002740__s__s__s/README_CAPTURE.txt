이 폴더는 TalkBack 디버그 분석용 캡처 결과입니다.

파일 설명
- meta.json: 캡처 시각, 기기, 입력값 등 메타데이터
- helper_dump_*: helper dump 원본/요약
- focus_payload.*: get_focus 응답
- focus_trace.json: get_focus 저장 메타
- window_dump.xml: UIAutomator 일반 XML dump
- screenshot.*: 스크린샷
- logcat_full.txt: 전체 logcat
- logcat_a11y_helper.txt: helper 관련 키워드만 필터한 로그
- capture_result.json: 각 단계 저장 결과 요약

스크린샷 설정
- format=jpg
- jpg_quality=88

권장 비교
1. screenshot에서 실제 보이는 객체 확인
2. window_dump.xml에서 raw tree 구조 확인
3. helper_dump에서 helper 후보/노드 구조 확인
4. focus_payload에서 현재 focus 판단 확인
5. logcat_a11y_helper.txt에서 smart move / get_focus 관련 로그 확인
