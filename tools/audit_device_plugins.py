import os
import sys
import json
import argparse
import subprocess
import re
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from tb_runner.scenario_config import TAB_CONFIGS
except ImportError as e:
    print(f"Warning: Could not import TAB_CONFIGS ({e})")
    TAB_CONFIGS = []

def get_device_plugins() -> List[str]:
    return [
        cfg["scenario_id"]
        for cfg in TAB_CONFIGS
        if cfg.get("scenario_id", "").startswith("device_") and cfg.get("scenario_id") != "devices_main"
    ]

def before_each_scenario_reset(serial: str, dry_run: bool) -> bool:
    if dry_run or not serial:
        return True
    try:
        subprocess.run(["adb", "-s", serial, "shell", "am", "force-stop", "com.samsung.android.oneconnect"], check=True, capture_output=True, timeout=10)
        subprocess.run(["adb", "-s", serial, "shell", "monkey", "-p", "com.samsung.android.oneconnect", "-c", "android.intent.category.LAUNCHER", "1"], check=True, capture_output=True, timeout=10)
        time.sleep(5)
        return True
    except Exception as e:
        print(f"Failed to reset app state: {e}")
        return False

def after_each_scenario_cleanup(serial: str, dry_run: bool):
    if dry_run or not serial:
        return
    try:
        subprocess.run(["adb", "-s", serial, "shell", "am", "force-stop", "com.samsung.android.oneconnect"], check=False, capture_output=True, timeout=10)
    except Exception:
        pass

def run_scenario_with_timeout(cmd: List[str], timeout: int) -> Dict[str, Any]:
    result = {"return_code": -1, "timed_out": False}
    try:
        proc = subprocess.run(cmd, timeout=timeout)
        result["return_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        result["timed_out"] = True
    except Exception as e:
        print(f"Error executing scenario: {e}")
    return result

def parse_summary_json(summary_path: Path) -> Dict[str, Any]:
    if not summary_path.exists():
        return {}
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def parse_run_results(log_path: Path, run_out_dir: Path) -> Dict[str, Any]:
    result = {
        "detected_tabs": [],
        "visited_tabs": [],
        "value_exclusion_warnings": [],
        "boundary_warnings": [],
        "repeat_warnings": [],
        "preflight_fail": False,
        "crash": False,
        "target_entered": None,
        "inventory_found": False,
        "stop_reason": "",
        "tab_stats": {}
    }
    
    xlsx_labels = {}
    if run_out_dir and run_out_dir.exists():
        xlsx_files = list(run_out_dir.glob("*.xlsx"))
        if xlsx_files:
            latest_xlsx = max(xlsx_files, key=os.path.getmtime)
            try:
                import pandas as pd
                df = pd.read_excel(latest_xlsx)
                tab_col = 'tab_name' if 'tab_name' in df.columns else 'tab' if 'tab' in df.columns else None
                label_col = 'visible_label' if 'visible_label' in df.columns else 'text' if 'text' in df.columns else None
                if tab_col and label_col:
                    for _, row in df.iterrows():
                        t = str(row[tab_col]).strip()
                        l = str(row[label_col]).strip()
                        if l and l.lower() not in ('nan', 'none', ''):
                            if t not in xlsx_labels:
                                xlsx_labels[t] = set()
                            xlsx_labels[t].add(l)
            except ImportError:
                pass
            except Exception as e:
                print(f"Error parsing xlsx {latest_xlsx}: {e}")

    for t in xlsx_labels:
        result["tab_stats"][t] = {
            "focus_count": 0,
            "representative_count": 0,
            "viewport_exhausted": False,
            "representative_exhausted": False,
            "repeat_no_progress": False,
            "last_focus_label": "",
            "last_representative_candidate": "",
            "unique_visible_labels": len(xlsx_labels[t]),
            "visible_labels_set": xlsx_labels[t]
        }

    if not log_path.exists():
        return result
        
    current_tab = ""

    def get_or_create_tab_stats(t_name):
        if t_name and t_name not in result["tab_stats"]:
            result["tab_stats"][t_name] = {
                "focus_count": 0,
                "representative_count": 0,
                "viewport_exhausted": False,
                "representative_exhausted": False,
                "repeat_no_progress": False,
                "last_focus_label": "",
                "last_representative_candidate": "",
                "unique_visible_labels": len(xlsx_labels.get(t_name, set())),
                "visible_labels_set": set(xlsx_labels.get(t_name, set()))
            }
        return result["tab_stats"].get(t_name)


    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "[PREFLIGHT]" in line and "fail" in line.lower() and "reason=" in line.lower():
                    result["preflight_fail"] = True
                
                if "[CRASH_GUARD]" in line and "running=false" in line.lower():
                    result["crash"] = True
                    
                if "kind='local_tab'" in line:
                    m = re.search(r"label='([^']+)'", line)
                    if m:
                        tab_name = m.group(1)
                        if tab_name in ("Play", "Next"):
                            continue
                        if tab_name not in result["detected_tabs"]:
                            result["detected_tabs"].append(tab_name)
                            
                if "[STEP][local_tab_transition_success]" in line or "[STEP][local_tab_force_navigation_resolved]" in line:
                    m = re.search(r"target='([^']+)'", line)
                    if m:
                        tab_name = m.group(1)
                        if tab_name in ("Play", "Next"):
                            continue
                        if tab_name not in result["visited_tabs"]:
                            result["visited_tabs"].append(tab_name)
                        current_tab = tab_name
                        get_or_create_tab_stats(current_tab)
                            
                if "[STEP][local_tab_active]" in line or "[STEP][local_tab_active_state]" in line:
                    m = re.search(r"active='([^']+)'", line)
                    if m:
                        tab_name = m.group(1)
                        if tab_name in ("Play", "Next"):
                            pass
                        elif tab_name != "none":
                            if tab_name not in result["visited_tabs"]:
                                result["visited_tabs"].append(tab_name)
                            current_tab = tab_name
                            get_or_create_tab_stats(current_tab)
                            
                if "[STEP] END" in line:
                    m = re.search(r"visible='([^']+)'", line)
                    if m and current_tab:
                        label = m.group(1).strip()
                        stats = get_or_create_tab_stats(current_tab)
                        stats["focus_count"] += 1
                        stats["last_focus_label"] = label
                        if label and label.lower() not in ('nan', 'none', ''):
                            stats["visible_labels_set"].add(label)
                            stats["unique_visible_labels"] = len(stats["visible_labels_set"])

                if "[STEP][focus_realign_record]" in line:
                    m = re.search(r"target='([^']+)'", line)
                    if m and current_tab:
                        label = m.group(1).strip()
                        stats = get_or_create_tab_stats(current_tab)
                        stats["representative_count"] += 1
                        stats["last_representative_candidate"] = label
                        if label and label.lower() not in ('nan', 'none', ''):
                            stats["visible_labels_set"].add(label)
                            stats["unique_visible_labels"] = len(stats["visible_labels_set"])

                if "[STEP][viewport_exhausted_eval]" in line or "[STEP][representative_exhausted_eval]" in line:
                    if current_tab:
                        stats = get_or_create_tab_stats(current_tab)
                        if "[STEP][viewport_exhausted_eval]" in line:
                            stats["viewport_exhausted"] = True
                        if "[STEP][representative_exhausted_eval]" in line:
                            stats["representative_exhausted"] = True
                    m_status = re.search(r"status_excluded='([^']+)'", line)
                    m_chrome = re.search(r"chrome_excluded='([^']+)'", line)
                    
                    status_ex = [x.strip().lower() for x in m_status.group(1).split('|') if x.strip()] if m_status and m_status.group(1) != 'none' else []
                    chrome_ex = [x.strip().lower() for x in m_chrome.group(1).split('|') if x.strip()] if m_chrome and m_chrome.group(1) != 'none' else []
                    
                    excluded = []
                    if m_status and m_status.group(1) != 'none':
                        excluded.extend([x.strip() for x in m_status.group(1).split('|') if x.strip()])
                    if m_chrome and m_chrome.group(1) != 'none':
                        excluded.extend([x.strip() for x in m_chrome.group(1).split('|') if x.strip()])
                        
                    for val in excluded:
                        vl = val.lower()
                        
                        # Suppress warnings for known harmless exclusions
                        if vl in chrome_ex and (vl in ["on", "off"] or "vibration sensor" in vl):
                            continue
                        if vl in status_ex and vl in ["online", "offline"]:
                            continue
                            
                        if (
                            "motion" in vl or "vibration" in vl or "°" in vl or "battery" in vl 
                            or re.search(r"\d+[\.,]?\d*\s*[°c]\w*", vl)
                            or re.fullmatch(r"\d+%", vl)
                            or vl in ["open", "closed", "detected", "clear", "dry", "wet", "on", "off", "online", "offline"]
                        ):
                            if val not in result["value_exclusion_warnings"]:
                                result["value_exclusion_warnings"].append(val)
                
                if "[PLUGIN_BOUNDARY][global_nav_reached]" in line:
                    m = re.search(r"label='([^']+)'", line)
                    if m:
                        result["boundary_warnings"].append(f"global_nav_reached: {m.group(1)[:30]}")
                        
                if "[STOP][eval]" in line and "reason='repeat_no_progress'" in line:
                    result["repeat_warnings"].append("repeat_no_progress")
                    if current_tab:
                        get_or_create_tab_stats(current_tab)["repeat_no_progress"] = True
                    
                if "[STEP][enter_device_card_success]" in line:
                    m = re.search(r"target='([^']+)'", line)
                    if m:
                        result["target_entered"] = m.group(1)
                        
                if "[DEVICE_ENTRY][safe_tap]" in line:
                    m = re.search(r"stable='([^']+)'", line)
                    if not m:
                        m = re.search(r"label='([^']+)'", line)
                    if m:
                        result["target_entered"] = m.group(1)
                        
                if "[INVENTORY]" in line and "found=true" in line:
                    result["inventory_found"] = True
                    
                if "[DEVICE_ENTRY][inventory]" in line:
                    m = re.search(r"count=(\d+)", line)
                    if m and int(m.group(1)) > 0:
                        result["inventory_found"] = True
                        
                if "[STOP][summary]" in line:
                    m = re.search(r"reason='([^']+)'", line)
                    if m:
                        result["stop_reason"] = m.group(1)

    except Exception as e:
        print(f"Error parsing log {log_path}: {e}")
        
    return result

def evaluate_scenario(scenario_id: str, summary: Dict[str, Any], log_data: Dict[str, Any]) -> Dict[str, Any]:
    target = ""
    scenario_info = next((s for s in summary.get("scenarios", []) if s.get("id") == scenario_id), {})
    if not scenario_info and "scenarios" in summary and len(summary["scenarios"]) == 1:
        scenario_info = summary["scenarios"][0]
        
    avail_status = scenario_info.get("availability_status", "none")
    
    # Infer availability if summary is empty
    if avail_status == "none" and not log_data["target_entered"] and log_data["inventory_found"] and not log_data["crash"]:
        avail_status = "not_available"
        
    avail_target = scenario_info.get("availability_target", "")
    stop_reason = scenario_info.get("stop_reason", "") or log_data.get("stop_reason", "")
    target = avail_target or log_data["target_entered"] or "Unknown"
    
    verdict = "UNKNOWN"
    reason = []
    
    detected = log_data["detected_tabs"]
    visited = log_data["visited_tabs"]
    missing_tabs = [t for t in detected if t not in visited]
    
    # Coverage logic
    tab_stats = log_data.get("tab_stats", {})
    all_tabs_exhausted = True
    coverage_warnings = []
    missing_content = []
    
    for t in visited:
        stats = tab_stats.get(t, {})
        is_exhausted = stats.get("viewport_exhausted") or stats.get("representative_exhausted")
        unique_labels = stats.get("unique_visible_labels", 0)
        if not is_exhausted:
            all_tabs_exhausted = False
            coverage_warnings.append(f"{t} not exhausted")
            
        if unique_labels < 1:
            coverage_warnings.append(f"{t} has no visible labels")
            
        if not is_exhausted and unique_labels == 0:
            coverage_warnings.append(f"{t} skipped immediately")

    # Plugin specific rules
    if scenario_id == "device_motion_sensor_plugin" and "Controls" in tab_stats:
        controls_labels = tab_stats["Controls"].get("visible_labels_set", set())
        controls_text = " ".join(controls_labels).lower()
        has_motion = "motion sensor" in controls_text or "no motion" in controls_text
        has_vib = "vibration sensor" in controls_text
        has_temp = "temperature" in controls_text or re.search(r"(\d+\s*degree|℃|℉|°c|°f)", controls_text)
        has_batt = "battery" in controls_text or "%" in controls_text
        
        if not has_motion: missing_content.append("Motion sensor status")
        if not has_vib: missing_content.append("Vibration sensor")
        if not has_temp: missing_content.append("Temperature")
        if not has_batt: missing_content.append("Battery")

    # Base failure states
    if log_data["preflight_fail"]:
        verdict = "ENVIRONMENT_ERROR"
        reason.append("Preflight failed")
    elif log_data["crash"]:
        verdict = "ENVIRONMENT_ERROR"
        reason.append("Crash detected")
    elif avail_status == "not_available":
        if log_data["target_entered"]:
            verdict = "FAIL"
            reason.append("Target entered but exited with not_available")
        else:
            verdict = "PASS_NOT_AVAILABLE"
            reason.append("Target not found, exited correctly")
    else:
        # Expected to be running
        if stop_reason == "plugin_boundary_global_nav" and "routines" in "".join(log_data["boundary_warnings"]).lower():
            # Might be local tab false positive
            verdict = "REVIEW"
            reason.append("global_nav_reached routines")
            
        if log_data["value_exclusion_warnings"]:
            verdict = "REVIEW"
            reason.append("Sensor values excluded")
            
        if missing_tabs and len(detected) > 0:
            verdict = "REVIEW"
            reason.append(f"Missed tabs: {', '.join(missing_tabs)}")
            
        if missing_content:
            verdict = "REVIEW"
            reason.append("missing content coverage")
            
        if coverage_warnings:
            verdict = "REVIEW"
            reason.append(f"Coverage issue: {', '.join(coverage_warnings)}")

        if log_data["repeat_warnings"]:
            if (
                log_data["target_entered"] 
                and len(detected) > 0 
                and not missing_tabs 
                and not log_data["boundary_warnings"] 
                and not log_data["value_exclusion_warnings"]
                and not log_data["crash"]
                and not log_data["preflight_fail"]
                and not missing_content
                and not coverage_warnings
                and (not stop_reason or stop_reason == "repeat_no_progress")
                and all(w == "repeat_no_progress" for w in log_data["repeat_warnings"])
            ):
                if all_tabs_exhausted:
                    if verdict == "UNKNOWN":
                        verdict = "PASS"
                        reason.append("All detected tabs visited; repeat_no_progress after exhaustion")
                else:
                    verdict = "REVIEW"
                    reason.append("repeat_no_progress before exhaustion")
            else:
                verdict = "REVIEW"
                reason.append("repeat_no_progress")
            
        if verdict == "UNKNOWN":
            if log_data["target_entered"]:
                verdict = "PASS"
                reason.append("All detected tabs visited, exhausted, and content present")
            else:
                if not log_data["inventory_found"]:
                    verdict = "ENVIRONMENT_ERROR"
                    reason.append("Failed to reach device inventory")
                else:
                    verdict = "FAIL"
                    reason.append("Target was not entered, nor marked not_available")
            
        if not detected and verdict == "PASS":
            reason.append("(0 local tabs detected)")

    tabs_exhausted_info = []
    tab_coverage_summary = []
    for t, stats in tab_stats.items():
        is_exh = stats.get("viewport_exhausted") or stats.get("representative_exhausted")
        tabs_exhausted_info.append(f"{t}: {is_exh}")
        tab_coverage_summary.append(f"{t} (U: {stats.get('unique_visible_labels')}, F: {stats.get('focus_count')}, R: {stats.get('representative_count')})")

    return {
        "scenario_id": scenario_id,
        "target": target,
        "verdict": verdict,
        "reason": " | ".join(reason),
        "availability_status": avail_status or "none",
        "entered_label": log_data["target_entered"] or "none",
        "detected_tabs": ", ".join(detected),
        "visited_tabs": ", ".join(visited),
        "missing_tabs": ", ".join(missing_tabs),
        "value_exclusion_warnings": ", ".join(log_data["value_exclusion_warnings"]),
        "boundary_warnings": ", ".join(log_data["boundary_warnings"]),
        "repeat_warnings": ", ".join(log_data["repeat_warnings"]),
        "tab_coverage_summary": " | ".join(tab_coverage_summary),
        "missing_content": ", ".join(missing_content),
        "tabs_exhausted": ", ".join(tabs_exhausted_info),
        "coverage_warnings": ", ".join(coverage_warnings)
    }

def main():
    parser = argparse.ArgumentParser(description="Audit device plugins automatically")
    parser.add_argument("--device", "--serial", dest="serial", help="Device serial number")
    parser.add_argument("--scenarios", nargs="+", help="Specific scenario IDs to run")
    parser.add_argument("--max-plugins", default="all", help="Max number of plugins to run (int or 'all')")
    parser.add_argument("--output-dir", required=True, help="Output directory for reports")
    parser.add_argument("--dry-run", action="store_true", help="Do not execute script_test.py, only parse existing logs")
    
    args = parser.parse_args()
    
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    if args.scenarios:
        scenarios = args.scenarios
    else:
        scenarios = get_device_plugins()
        
    if args.max_plugins.lower() != "all":
        try:
            limit = int(args.max_plugins)
            scenarios = scenarios[:limit]
        except ValueError:
            pass
            
    print(f"Starting audit for {len(scenarios)} scenarios...")
    
    results = []
    
    for sid in scenarios:
        print(f"\n--- Auditing {sid} ---")
        run_out_dir = out_dir / sid
        
        exec_info = {"return_code": "N/A", "timed_out": False, "start_recovered": False}
        
        if not args.dry_run and args.serial:
            exec_info["start_recovered"] = before_each_scenario_reset(args.serial, args.dry_run)
            
            cmd = [
                sys.executable, "script_test.py",
                "--serial", args.serial,
                "--scenario", sid,
                "--output-dir", str(run_out_dir)
            ]
            print(f"Executing: {' '.join(cmd)}")
            res = run_scenario_with_timeout(cmd, timeout=300)
            exec_info["return_code"] = res["return_code"]
            exec_info["timed_out"] = res["timed_out"]
            
            after_each_scenario_cleanup(args.serial, args.dry_run)
        else:
            if not args.dry_run:
                print("Skipping execution because --device/--serial is not provided.")
                
        # Parse logs
        summary_file = run_out_dir / "summary.json"
        
        # Find normal log
        normal_log = None
        if run_out_dir.exists():
            logs = list(run_out_dir.glob("*.normal.log"))
            if logs:
                normal_log = max(logs, key=os.path.getmtime)
                
        if not summary_file.exists() and not normal_log:
            print(f"No logs found for {sid} in {run_out_dir}")
            results.append({
                "scenario_id": sid,
                "target": "N/A",
                "verdict": "FAIL",
                "reason": "No logs found",
                "availability_status": "none",
                "entered_label": "none",
                "detected_tabs": "",
                "visited_tabs": "",
                "missing_tabs": "",
                "value_exclusion_warnings": "",
                "boundary_warnings": "",
                "repeat_warnings": "",
                "tab_coverage_summary": "",
                "missing_content": "",
                "tabs_exhausted": "",
                "coverage_warnings": "",
                "return_code": exec_info["return_code"],
                "timed_out": exec_info["timed_out"],
                "start_recovered": exec_info["start_recovered"]
            })
            continue
            
        summary_data = parse_summary_json(summary_file)
        log_data = parse_run_results(normal_log, run_out_dir) if normal_log else parse_run_results(Path("nonexistent"), run_out_dir)

        
        report = evaluate_scenario(sid, summary_data, log_data)
        report["return_code"] = exec_info["return_code"]
        report["timed_out"] = exec_info["timed_out"]
        report["start_recovered"] = exec_info["start_recovered"]
        results.append(report)
        print(f"Verdict: {report['verdict']} - {report['reason']}")

    # Generate Reports
    json_path = out_dir / "audit_report.json"
    csv_path = out_dir / "audit_report.csv"
    md_path = out_dir / "audit_report.md"
    
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    if results:
        import csv
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=results[0].keys())
            writer.writeheader()
            writer.writerows(results)
            
    with open(md_path, "w", encoding="utf-8") as f:
        total = len(results)
        pass_count = sum(1 for r in results if r["verdict"] == "PASS")
        pass_na_count = sum(1 for r in results if r["verdict"] == "PASS_NOT_AVAILABLE")
        review_count = sum(1 for r in results if r["verdict"] == "REVIEW")
        fail_count = sum(1 for r in results if r["verdict"] == "FAIL")
        env_error_count = sum(1 for r in results if r["verdict"] == "ENVIRONMENT_ERROR")
        
        global_nav_issues = sum(1 for r in results if "global_nav_reached" in r["reason"])
        missed_tabs_issues = sum(1 for r in results if "Missed tabs" in r["reason"])
        value_exclusion_issues = sum(1 for r in results if "Sensor values excluded" in r["reason"])
        repeat_no_progress_issues = sum(1 for r in results if "repeat_no_progress" in r["reason"])
        env_issues = sum(1 for r in results if r["verdict"] == "ENVIRONMENT_ERROR")

        f.write("# Device Plugin Audit Report\n\n")
        f.write("## Audit Summary\n\n")
        f.write(f"Total: {total}\n")
        f.write(f"PASS: {pass_count}\n")
        f.write(f"PASS_NOT_AVAILABLE: {pass_na_count}\n")
        f.write(f"REVIEW: {review_count}\n")
        f.write(f"FAIL: {fail_count}\n")
        f.write(f"ENVIRONMENT_ERROR: {env_error_count}\n\n")
        
        f.write("Top Issues:\n")
        f.write(f"* environment_error: {env_issues}\n")
        f.write(f"* global_nav_reached: {global_nav_issues}\n")
        f.write(f"* missed_tabs: {missed_tabs_issues}\n")
        f.write(f"* value_exclusion: {value_exclusion_issues}\n")
        f.write(f"* repeat_no_progress: {repeat_no_progress_issues}\n\n")

        f.write("| Scenario ID | Verdict | Tabs | Tab Coverage | Missing Content | Reason |\n")
        f.write("|-------------|---------|------|--------------|-----------------|--------|\n")
        for r in results:
            f.write(f"| {r['scenario_id']} | {r['verdict']} | {r['detected_tabs']} | {r['tab_coverage_summary']} | {r['missing_content']} | {r['reason']} |\n")
            
    print(f"\nAudit complete. Reports saved to {out_dir}")

if __name__ == "__main__":
    main()
