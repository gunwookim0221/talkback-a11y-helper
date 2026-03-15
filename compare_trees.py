import os
import json
import subprocess
import xml.etree.ElementTree as ET
import re
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("[-] 오류: Pillow 라이브러리가 설치되지 않았습니다. 'pip install Pillow'를 실행해주세요.")
    sys.exit(1)

try:
    from talkback_lib import A11yAdbClient
    client = A11yAdbClient()
except ImportError:
    print("[-] 에러: 'talkback_lib.py' 파일을 찾을 수 없거나 A11yAdbClient 클래스가 없습니다.")
    sys.exit(1)

def get_default_device():
    """연결된 첫 번째 ADB 단말기의 시리얼 번호를 자동으로 가져옵니다."""
    try:
        result = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().split('\n')[1:]
        devices = [line.split('\t')[0] for line in lines if '\tdevice' in line]
        
        if devices:
            print(f"[*] 연결된 단말기 자동 감지: {devices[0]}")
            return devices[0]
        else:
            print("[-] 에러: 연결된 단말기(혹은 에뮬레이터)를 찾을 수 없습니다.")
            return None
    except Exception as e:
        print(f"[-] ADB 명령어 실행 중 에러 발생: {e}")
        return None

def get_legacy_tree(serial, local_path):
    print("\n[*] 1. 일반 트리를 추출합니다... (UI Automator 방식)")
    print("    (단말기에 앱 화면을 '일반 모드'로 띄워주세요)")
    
    remote_path = "/sdcard/legacy_dump.xml"
    subprocess.run(
        f"adb -s {serial} shell uiautomator dump {remote_path}", 
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    subprocess.run(
        f"adb -s {serial} pull {remote_path} {local_path}", 
        shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    
    if os.path.exists(local_path):
        print(f"  -> [+] '{local_path}' 파일 다운로드 완료")
        return True
    else:
        print(f"  [-] 에러: '{local_path}' 파일을 가져오지 못했습니다. 화면이 꺼져있거나 권한 문제일 수 있습니다.")
        return False

def get_a11y_tree(serial, local_path):
    print("\n[*] 2. 접근성 트리를 추출합니다... (TalkBack Helper 방식)")
    try:
        if hasattr(client, 'check_helper_status'):
            if not client.check_helper_status(serial):
                print("[-] 헬퍼 서비스가 READY 상태가 아닙니다. Helper 앱이 켜져있는지 확인하세요.")
                return False

        a11y_data = client.dump_tree(serial) 
        
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(a11y_data, f, ensure_ascii=False, indent=2)
            
        print(f"  -> [+] '{local_path}' 파일 다운로드 완료")
        return True
    except Exception as e:
        print(f"[-] 접근성 트리 추출 실패: {e}")
        return False

def compare_and_summarize(xml_path, json_path):
    print("\n" + "=" * 50)
    print(" 📊 시각 트리 vs 접근성 트리 분석 및 요약 리포트")
    print("=" * 50)

    xml_nodes = 0
    xml_clickable = 0
    try:
        tree = ET.parse(xml_path)
        for node in tree.getroot().iter('node'):
            xml_nodes += 1
            if node.get('clickable') == 'true':
                xml_clickable += 1
    except Exception as e:
        print(f"[!] XML 분석 실패: {e}")

    json_nodes = 0
    json_clickable = 0
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            json_nodes = len(data) if isinstance(data, list) else 1
            
            if isinstance(data, list):
                for item in data:
                    if item.get('clickable') is True or item.get('isClickable') is True:
                        json_clickable += 1
    except Exception as e:
        print(f"[!] JSON 분석 실패: {e}")

    filtered_count = xml_nodes - json_nodes
    compression_rate = (filtered_count / xml_nodes * 100) if xml_nodes > 0 else 0

    print(f"🔍 [전체 노드 수 비교]")
    print(f"  - 기존 UI 덤프 (XML) : {xml_nodes}개")
    print(f"  - 헬퍼 접근성 (JSON) : {json_nodes}개")
    print(f"  💡 분석: TalkBack에 불필요한 노드 {filtered_count}개(약 {compression_rate:.1f}%)가 완벽히 필터링되었습니다.")
    
    print(f"\n👆 [클릭 가능(Clickable) 노드 비교]")
    print(f"  - 기존 UI 덤프 (XML) : {xml_clickable}개")
    print(f"  - 헬퍼 접근성 (JSON) : {json_clickable}개")
    if xml_clickable > json_clickable:
        print(f"  💡 분석: 화면엔 보이지만 실제 시각장애인은 클릭할 수 없는 '가짜 버튼'이 약 {xml_clickable - json_clickable}개 존재합니다.")
    elif json_clickable > xml_clickable:
        print(f"  💡 분석: 여러 하위 노드가 병합(Merge)되어 접근성 전용 클릭 영역이 새로 생성되었습니다.")
    print("=" * 50)

def visualize_trees(serial):
    """스크린샷을 찍고 XML/JSON 좌표를 바탕으로 네모 박스를 그립니다."""
    print("\n[*] 3. 시각화 자료(이미지)를 생성합니다...")
    
    screenshot_path = "raw_screenshot.png"
    remote_screenshot = "/sdcard/raw_screenshot.png"
    
    print("  -> 스크린샷을 촬영 중입니다...")
    # 1. 단말기 내부에 캡처 (인코딩 깨짐 방지)
    subprocess.run(f"adb -s {serial} shell screencap -p {remote_screenshot}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 2. PC로 파일 가져오기
    subprocess.run(f"adb -s {serial} pull {remote_screenshot} {screenshot_path}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # 3. 단말기에 남은 찌꺼기 파일 삭제
    subprocess.run(f"adb -s {serial} shell rm {remote_screenshot}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not os.path.exists(screenshot_path):
        print("  [-] 에러: 스크린샷 캡처에 실패했습니다.")
        return

    # 3-1. 일반 UI (XML) 시각화 - 빨간색
    try:
        img_legacy = Image.open(screenshot_path).convert("RGBA")
        draw_legacy = ImageDraw.Draw(img_legacy)
        tree = ET.parse("legacy_tree.xml")
        bounds_pattern = re.compile(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
        
        for node in tree.getroot().iter('node'):
            bounds_str = node.attrib.get('bounds')
            if bounds_str:
                match = bounds_pattern.match(bounds_str)
                if match:
                    x1, y1, x2, y2 = map(int, match.groups())
                    draw_legacy.rectangle([x1, y1, x2, y2], outline="red", width=5)
        
        img_legacy.save("legacy_view.png")
        print("  -> [+] 'legacy_view.png' 생성 완료 (빨간색 박스)")
    except Exception as e:
        print(f"  [-] XML 이미지 생성 실패: {e}")

    # 3-2. 접근성 트리 (JSON) 시각화 - 초록색
    try:
        img_a11y = Image.open(screenshot_path).convert("RGBA")
        draw_a11y = ImageDraw.Draw(img_a11y)
        bounds_pattern = re.compile(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]')
        
        with open("a11y_tree.json", 'r', encoding='utf-8') as f:
            a11y_data = json.load(f)
            
        nodes = a11y_data if isinstance(a11y_data, list) else a11y_data.get('nodes', [])
        for node in nodes:
            bounds = node.get('boundsInScreen') or node.get('bounds')
            
            if isinstance(bounds, dict):
                x1, y1 = bounds.get('l', 0), bounds.get('t', 0)
                x2, y2 = bounds.get('r', 0), bounds.get('b', 0)
                draw_a11y.rectangle([x1, y1, x2, y2], outline="#00FF00", width=8)
            elif isinstance(bounds, str):
                match = bounds_pattern.match(bounds)
                if match:
                    x1, y1, x2, y2 = map(int, match.groups())
                    draw_a11y.rectangle([x1, y1, x2, y2], outline="#00FF00", width=8)
                
        img_a11y.save("a11y_view.png")
        print("  -> [+] 'a11y_view.png' 생성 완료 (초록색 박스)")
    except Exception as e:
        print(f"  [-] JSON 이미지 생성 실패: {e}")
        
    print("\n🎉 모든 작업이 완료되었습니다! 폴더에 생성된 이미지를 확인해 보세요.")
def main():
    print("🚀 앱 화면 구조 자동 추출 및 비교 도구 시작")
    
    dev_serial = get_default_device()
    if not dev_serial:
        return

    xml_file = "legacy_tree.xml"
    json_file = "a11y_tree.json"

    if os.path.exists(xml_file): os.remove(xml_file)
    if os.path.exists(json_file): os.remove(json_file)

    get_legacy_tree(dev_serial, xml_file)
    
    print("\n" + "#" * 50)
    print("  ⏳ [대기 중] 단말기에서 'TalkBack'을 켜주세요.")
    print("     (화면 상태가 바뀐 것을 확인한 후 아래에서 엔터를 치세요)")
    print("#" * 50)
    input("  >> 준비가 완료되면 [Enter] 키를 누르세요...")
    
    success = get_a11y_tree(dev_serial, json_file)
    
    if success and os.path.exists(xml_file) and os.path.exists(json_file):
        compare_and_summarize(xml_file, json_file)
        
        # 여기서 시각화 함수를 호출하며 dev_serial 변수를 넘겨줍니다!
        visualize_trees(dev_serial)
    else:
        print("\n[-] 파일 추출이 정상적으로 완료되지 않아 비교를 건너뜁니다.")

if __name__ == "__main__":
    main()
