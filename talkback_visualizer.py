import os
import subprocess
import xml.etree.ElementTree as ET
import cv2
import time
from datetime import datetime

# --- 설정 ---
ADB_CMD = "adb" 
OUTPUT_DIR = "a11y_result"

def run_adb_cmd(cmd):
    full_cmd = f"{ADB_CMD} {cmd}"
    try:
        result = subprocess.run(full_cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return result.stdout.decode('utf-8')
    except subprocess.CalledProcessError as e:
        print(f"ADB 에러: {e.stderr.decode('utf-8')}")
        return None

def get_android_screen(filename_prefix):
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        
    local_png = os.path.join(OUTPUT_DIR, f"{filename_prefix}.png")
    local_xml = os.path.join(OUTPUT_DIR, f"{filename_prefix}.xml")
    
    print(f"[{filename_prefix}] 화면 캡처 및 트리 덤프 중...")
    run_adb_cmd(f"shell screencap -p /sdcard/screen.png")
    run_adb_cmd(f"pull /sdcard/screen.png {local_png}")
    run_adb_cmd(f"shell uiautomator dump /sdcard/window_dump.xml")
    run_adb_cmd(f"pull /sdcard/window_dump.xml {local_xml}")
    run_adb_cmd(f"shell rm /sdcard/screen.png /sdcard/window_dump.xml")
    
    return local_png, local_xml

def parse_bounds(bounds_str):
    clean_bounds = bounds_str.replace("][", ",").replace("[", "").replace("]", "")
    try:
        x1, y1, x2, y2 = map(int, clean_bounds.split(','))
        return (x1, y1), (x2, y2)
    except ValueError:
        return None, None

def draw_ax_boxes(png_file, xml_file, state_name):
    if not os.path.exists(png_file) or not os.path.exists(xml_file): return
    img = cv2.imread(png_file)
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
    except: return

    for node in root.iter('node'):
        if node.get('clickable') == 'true' or node.get('focusable') == 'true':
            p1, p2 = parse_bounds(node.get('bounds'))
            if p1 and p2:
                cv2.rectangle(img, p1, p2, (0, 0, 255), 3)

    out_path = os.path.join(OUTPUT_DIR, f"drawn_{state_name}.png")
    cv2.imwrite(out_path, img)
    print(f"[{state_name}] 사각형 그리기 완료: {out_path}")

# --- 새롭게 추가된 트리 분석 엔진 ---
def analyze_tree(xml_file):
    """XML 트리를 파싱하여 주요 통계와 데이터를 추출합니다."""
    tree_data = {
        "total_nodes": 0,
        "interactive_nodes": 0, # clickable or focusable
        "resource_ids": set(),
        "hidden_descriptions": [] # text는 없는데 content-desc만 있는 노드
    }
    
    if not os.path.exists(xml_file):
        return tree_data

    tree = ET.parse(xml_file)
    root = tree.getroot()

    for node in root.iter('node'):
        tree_data["total_nodes"] += 1
        
        is_interactive = (node.get('clickable') == 'true' or node.get('focusable') == 'true')
        if is_interactive:
            tree_data["interactive_nodes"] += 1

        res_id = node.get('resource-id')
        if res_id:
            tree_data["resource_ids"].add(res_id)

        text = node.get('text', '')
        desc = node.get('content-desc', '')
        
        # 핵심 분석: 눈에 보이는 text는 없지만, TalkBack이 읽어주는 desc가 있는 경우
        if not text and desc:
            tree_data["hidden_descriptions"].append({
                "desc": desc,
                "bounds": node.get('bounds'),
                "id": res_id
            })

    return tree_data

def compare_trees(xml_off, xml_on):
    """두 상태의 트리를 비교 분석하여 리포트를 출력합니다."""
    print("\n" + "="*50)
    print("📊 TalkBack ON/OFF 트리 비교 분석 리포트")
    print("="*50)
    
    stats_off = analyze_tree(xml_off)
    stats_on = analyze_tree(xml_on)

    # 1. 노드 밀도 (Density & Grouping)
    print("\n[1] 노드 개수 변화 (Grouping 효과 확인)")
    print(f" - OFF 상태 총 노드 수: {stats_off['total_nodes']} 개")
    print(f" - ON  상태 총 노드 수: {stats_on['total_nodes']} 개")
    diff_nodes = stats_off['total_nodes'] - stats_on['total_nodes']
    if diff_nodes > 0:
        print(f"   💡 결론: TalkBack이 켜지면서 {diff_nodes}개의 노드가 논리적으로 병합되거나 숨겨졌습니다.")
    else:
        print("   💡 결론: 노드 수에 큰 변화가 없습니다.")

    # 2. 숨겨진 음성 정보 (contentDescription)
    print("\n[2] 숨겨진 음성 텍스트 (Hidden contentDescription)")
    print(f" - OFF 상태 발견: {len(stats_off['hidden_descriptions'])} 개")
    print(f" - ON  상태 발견: {len(stats_on['hidden_descriptions'])} 개")
    
    if stats_on['hidden_descriptions']:
        print("   [ON 상태에서 읽어주는 숨겨진 텍스트 목록]")
        for item in stats_on['hidden_descriptions'][:5]: # 너무 많을 수 있으니 5개만 출력
            print(f"     * '{item['desc']}' (위치: {item['bounds']}, ID: {item['id']})")
        if len(stats_on['hidden_descriptions']) > 5:
            print("     ... (생략)")

    # 3. 리소스 ID 매칭 (TalkBack ON 상태에서 새로 잡히거나 누락되는 ID)
    ids_off = stats_off['resource_ids']
    ids_on = stats_on['resource_ids']
    
    missing_in_on = ids_off - ids_on
    new_in_on = ids_on - ids_off

    print("\n[3] 리소스 ID (resource-id) 변화")
    print(f" - 공통으로 존재하는 ID: {len(ids_off & ids_on)} 개")
    print(f" - OFF에만 있는 ID (ON에서 숨겨짐): {len(missing_in_on)} 개")
    print(f" - ON에만 있는 ID (가상 노드 생성됨): {len(new_in_on)} 개")
    
    if missing_in_on:
        print(f"   💡 ON에서 무시된 주요 ID (예시): {list(missing_in_on)[:3]}")
    if new_in_on:
        print(f"   💡 ON에서 새로 생성된 ID (예시): {list(new_in_on)[:3]}")
    print("="*50 + "\n")

# --- 메인 실행 루프 ---
def main():
    print("=== Android Accessibility 분석기 ===")
    xml_off = os.path.join(OUTPUT_DIR, "talkback_OFF.xml")
    xml_on = os.path.join(OUTPUT_DIR, "talkback_ON.xml")
    
    while True:
        print("\n1. [TalkBack OFF] 캡처")
        print("2. [TalkBack ON] 캡처 (폰에서 직접 켠 후 실행)")
        print("3. 📊 두 상태 트리를 비교 분석하기 (1, 2번 완료 후 실행)")
        print("q. 종료")
        choice = input("선택: ").strip().lower()
        
        if choice == '1':
            png, xml_off = get_android_screen("talkback_OFF")
            draw_ax_boxes(png, xml_off, "OFF")
        elif choice == '2':
            png, xml_on = get_android_screen("talkback_ON")
            draw_ax_boxes(png, xml_on, "ON")
        elif choice == '3':
            if os.path.exists(xml_off) and os.path.exists(xml_on):
                compare_trees(xml_off, xml_on)
            else:
                print("❌ 에러: 비교를 위해 1번과 2번을 먼저 실행해야 합니다.")
        elif choice == 'q':
            break

if __name__ == "__main__":
    main()