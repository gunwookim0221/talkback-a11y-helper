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

def parse_normal_log(log_path: Path) -> Dict[str, Any]:
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
        "stop_reason": ""
    }
    
    if not log_path.exists():
        return result
        
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
                        if tab_name not in result["detected_tabs"]:
                            result["detected_tabs"].append(tab_name)
                            
                if "[STEP][local_tab_transition_success]" in line or "[STEP][local_tab_force_navigation_resolved]" in line:
                    m = re.search(r"target='([^']+)'", line)
                    if m:
                        tab_name = m.group(1)
                        if tab_name not in result["visited_tabs"]:
                            result["visited_tabs"].append(tab_name)
                            
                if "[STEP][viewport_exhausted_eval]" in line or "[STEP][representative_exhausted_eval]" in line:
                    m_status = re.search(r"status_excluded='([^']+)'", line)
                    m_chrome = re.search(r"chrome_excluded='([^']+)'", line)
                    excluded = []
                    if m_status and m_status.group(1) != 'none':
                        excluded.extend([x.strip() for x in m_status.group(1).split('|') if x.strip()])
                    if m_chrome and m_chrome.group(1) != 'none':
                        excluded.extend([x.strip() for x in m_chrome.group(1).split('|') if x.strip()])
                        
                    for val in excluded:
                        vl = val.lower()
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
            
        if log_data["repeat_warnings"]:
            if (
                log_data["target_entered"] 
                and len(detected) > 0 
                and not missing_tabs 
                and not log_data["boundary_warnings"] 
                and not log_data["value_exclusion_warnings"]
                and not log_data["crash"]
                and not log_data["preflight_fail"]
                and (not stop_reason or stop_reason == "repeat_no_progress")
                and all(w == "repeat_no_progress" for w in log_data["repeat_warnings"])
            ):
                if verdict == "UNKNOWN":
                    verdict = "PASS"
                    reason.append("All detected tabs visited; repeat_no_progress after exhaustion")
            else:
                verdict = "REVIEW"
                reason.append("repeat_no_progress")
            
        if verdict == "UNKNOWN":
            if log_data["target_entered"]:
                verdict = "PASS"
                reason.append("All detected tabs visited, no warnings")
            else:
                if not log_data["inventory_found"]:
                    verdict = "ENVIRONMENT_ERROR"
                    reason.append("Failed to reach device inventory")
                else:
                    verdict = "FAIL"
                    reason.append("Target was not entered, nor marked not_available")
            
        if not detected and verdict == "PASS":
            reason.append("(0 local tabs detected)")

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
        "repeat_warnings": ", ".join(log_data["repeat_warnings"])
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
                "return_code": exec_info["return_code"],
                "timed_out": exec_info["timed_out"],
                "start_recovered": exec_info["start_recovered"]
            })
            continue
            
        summary_data = parse_summary_json(summary_file)
        log_data = parse_normal_log(normal_log) if normal_log else parse_normal_log(Path("nonexistent"))
        
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

        f.write("| Scenario ID | Verdict | Reason | Target | Return Code | Timed Out | Recovered | Missing Tabs | Exclusion Warnings |\n")
        f.write("|-------------|---------|--------|--------|-------------|-----------|-----------|--------------|--------------------|\n")
        for r in results:
            f.write(f"| {r['scenario_id']} | {r['verdict']} | {r['reason']} | {r['target']} | {r.get('return_code', 'N/A')} | {r.get('timed_out', False)} | {r.get('start_recovered', False)} | {r['missing_tabs']} | {r['value_exclusion_warnings']} |\n")
            
    print(f"\nAudit complete. Reports saved to {out_dir}")

if __name__ == "__main__":
    main()
