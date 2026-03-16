import os
import json
import subprocess
import xml.etree.ElementTree as ET
import re
import sys
from datetime import datetime

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
        print(f"  -> [+] '{os.path.basename(local_path)}' 다운로드 완료")
        return True
    else:
        print(f"  [-] 에러: '{local_path}' 파일을 가져오지 못했습니다.")
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
            
        print(f"  -> [+] '{os.path.basename(local_path)}' 다운로드 완료")
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
    print(f"  💡 분석: TalkBack에 불필요한 노드 {filtered_count}개(약 {compression_rate:.1f}%)가 필터링되었습니다.")
    
    print(f"\n👆 [클릭 가능(Clickable) 노드 비교]")
    print(f"  - 기존 UI 덤프 (XML) : {xml_clickable}개")
    print(f"  - 헬퍼 접근성 (JSON) : {json_clickable}개")
    if xml_clickable > json_clickable:
        print(f"  💡 분석: 화면엔 보이지만 실제로는 클릭할 수 없는 '가짜 버튼'이 약 {xml_clickable - json_clickable}개 존재합니다.")
    elif json_clickable > xml_clickable:
        print(f"  💡 분석: 여러 하위 노드가 병합(Merge)되어 접근성 전용 클릭 영역이 새로 생성되었습니다.")
    print("=" * 50)

def extract_valid_bounds(bounds, pattern):
    """좌표 데이터를 파싱하고 안전하게 정렬하여 반환하는 헬퍼 함수"""
    x_start, y_start, x_end, y_end = 0, 0, 0, 0
    valid = False
    
    if isinstance(bounds, dict):
        x_start, y_start = bounds.get('l', 0), bounds.get('t', 0)
        x_end, y_end = bounds.get('r', 0), bounds.get('b', 0)
        valid = True
    elif isinstance(bounds, str):
        match = pattern.match(bounds)
        if match:
            x_start, y_start, x_end, y_end = map(int, match.groups())
            valid = True
            
    if valid:
        x1, x2 = min(x_start, x_end), max(x_start, x_end)
        y1, y2 = min(y_start, y_end), max(y_start, y_end)
        if x2 > x1 and y2 > y1:
            return [x1, y1, x2, y2]
    return None

def visualize_trees(serial, output_dir, timestamp, xml_file, json_file, json_clickable_file):
    print("\n[*] 3. 시각화 자료(이미지)를 생성합니다...")
    
    screenshot_path = os.path.join(output_dir, f"{timestamp}_raw_screenshot.png")
    remote_screenshot = "/sdcard/raw_screenshot.png"
    
    print("  -> 스크린샷을 촬영 중입니다...")
    subprocess.run(f"adb -s {serial} shell screencap -p {remote_screenshot}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(f"adb -s {serial} pull {remote_screenshot} {screenshot_path}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(f"adb -s {serial} shell rm {remote_screenshot}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not os.path.exists(screenshot_path):
        print("  [-] 에러: 스크린샷 캡처에 실패했습니다.")
        return

    bounds_pattern = re.compile(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]')

    # 3-1. 일반 UI (XML) 시각화 - 빨간색
    try:
        img_legacy = Image.open(screenshot_path).convert("RGBA")
        draw_legacy = ImageDraw.Draw(img_legacy)
        tree = ET.parse(xml_file)
        
        count = 0
        for node in tree.getroot().iter('node'):
            bounds_str = node.attrib.get('bounds')
            if bounds_str:
                box = extract_valid_bounds(bounds_str, bounds_pattern)
                if box:
                    draw_legacy.rectangle(box, outline="red", width=5)
                    count += 1
        
        legacy_img_out = os.path.join(output_dir, f"{timestamp}_legacy_view.png")
        img_legacy.save(legacy_img_out)
        print(f"  -> [+] '{os.path.basename(legacy_img_out)}' 생성 완료 (빨간색 박스: {count}개)")
    except Exception as e:
        print(f"  [-] XML 이미지 생성 실패: {e}")

    # 3-2. 접근성 트리 전체 (JSON) 시각화 - 초록색
    try:
        img_a11y = Image.open(screenshot_path).convert("RGBA")
        draw_a11y = ImageDraw.Draw(img_a11y)
        
        with open(json_file, 'r', encoding='utf-8') as f:
            a11y_data = json.load(f)
            
        nodes = a11y_data if isinstance(a11y_data, list) else a11y_data.get('nodes', [])
        count = 0
        for node in nodes:
            bounds = node.get('boundsInScreen') or node.get('bounds')
            box = extract_valid_bounds(bounds, bounds_pattern)
            if box:
                draw_a11y.rectangle(box, outline="#00FF00", width=8)
                count += 1
                
        a11y_img_out = os.path.join(output_dir, f"{timestamp}_a11y_view.png")
        img_a11y.save(a11y_img_out)
        print(f"  -> [+] '{os.path.basename(a11y_img_out)}' 생성 완료 (초록색 박스: {count}개)")
    except Exception as e:
        print(f"  [-] JSON 이미지 생성 실패: {e}")

    # 3-3. 접근성 트리 Clickable Only (JSON) 시각화 - 파란색
    try:
        img_a11y_click = Image.open(screenshot_path).convert("RGBA")
        draw_a11y_click = ImageDraw.Draw(img_a11y_click)
        
        with open(json_clickable_file, 'r', encoding='utf-8') as f:
            clickable_data = json.load(f)
            
        count = 0
        for node in clickable_data:
            bounds = node.get('boundsInScreen') or node.get('bounds')
            box = extract_valid_bounds(bounds, bounds_pattern)
            if box:
                # Clickable 객체는 파란색(DeepSkyBlue)으로 강조
                draw_a11y_click.rectangle(box, outline="#00BFFF", width=10)
                count += 1
                
        a11y_click_img_out = os.path.join(output_dir, f"{timestamp}_a11y_clickable_view.png")
        img_a11y_click.save(a11y_click_img_out)
        print(f"  -> [+] '{os.path.basename(a11y_click_img_out)}' 생성 완료 (파란색 박스: {count}개)")
    except Exception as e:
        print(f"  [-] Clickable JSON 이미지 생성 실패: {e}")
        
    print(f"\n🎉 모든 작업이 완료되었습니다! '{output_dir}' 폴더를 확인해 보세요.")

def main():
    print("🚀 앱 화면 구조 자동 추출 및 비교 도구 시작")
    
    dev_serial = get_default_device()
    if not dev_serial:
        return

    # 1. 결과를 저장할 폴더 생성
    output_dir = "compare_result"
    os.makedirs(output_dir, exist_ok=True)

    # 2. 실행 시간을 기반으로 한 고유 타임스탬프 생성 (예: 20240520_153022)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 3. 타임스탬프가 붙은 파일 경로 설정
    xml_file = os.path.join(output_dir, f"{timestamp}_legacy_tree.xml")
    json_file = os.path.join(output_dir, f"{timestamp}_a11y_tree.json")
    json_clickable_file = os.path.join(output_dir, f"{timestamp}_a11y_clickable_tree.json")

    # 일반 트리 덤프
    get_legacy_tree(dev_serial, xml_file)
    
    print("\n" + "#" * 50)
    print("  ⏳ [대기 중] 단말기에서 'TalkBack'을 켜주세요.")
    print("     (화면 상태가 바뀐 것을 확인한 후 아래에서 엔터를 치세요)")
    print("#" * 50)
    input("  >> 준비가 완료되면 [Enter] 키를 누르세요...")
    
    # 접근성 트리 덤프
    success = get_a11y_tree(dev_serial, json_file)
    
    if success and os.path.exists(xml_file) and os.path.exists(json_file):
        compare_and_summarize(xml_file, json_file)
        
        # 4. Clickable 객체만 필터링하여 새로운 JSON으로 저장
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                a11y_data = json.load(f)
            nodes = a11y_data if isinstance(a11y_data, list) else a11y_data.get('nodes', [])
            
            # clickable이 true인 노드만 수집
            clickable_nodes = [n for n in nodes if n.get('clickable') is True or n.get('isClickable') is True]
            
            with open(json_clickable_file, 'w', encoding='utf-8') as f:
                json.dump(clickable_nodes, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            print(f"[-] Clickable JSON 데이터 분류 중 오류: {e}")
        
        # 5. 세 가지 버전의 시각화 실행
        visualize_trees(dev_serial, output_dir, timestamp, xml_file, json_file, json_clickable_file)
    else:
        print("\n[-] 파일 추출이 정상적으로 완료되지 않아 비교를 건너뜁니다.")

if __name__ == "__main__":
    main()
