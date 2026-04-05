from pathlib import Path

from talkback_lib import A11yAdbClient
from tb_runner.collection_flow import collect_tab_rows, recover_to_start_state
from tb_runner.anchor_logic import choose_best_anchor_candidate, match_anchor, stabilize_anchor
from tb_runner.context_verifier import verify_context
from tb_runner.diagnostics import detect_step_mismatch, should_stop
from tb_runner.overlay_logic import (
    classify_post_click_result,
    expand_overlay,
    is_overlay_candidate,
    realign_focus_after_overlay,
)
from tb_runner.tab_logic import (
    choose_best_tab_candidate,
    match_tab_candidate,
    normalize_tab_config,
    stabilize_tab_selection,
)
from tb_runner.constants import DEV_SERIAL, LOG_LEVEL, SCRIPT_VERSION
from tb_runner.excel_report import save_excel
from tb_runner.logging_utils import close_log_files, configure_log_files, log
from tb_runner.perf_stats import RunPerfStats, format_perf_summary, save_excel_with_perf
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.runtime_config import load_runtime_bundle
from tb_runner.utils import generate_output_path


def main():
    output_path = generate_output_path()
    output_base_dir = str(Path(output_path).with_suffix(""))
    configure_log_files(output_path)

    log(f"[MAIN] script start (version={SCRIPT_VERSION}, log_level={LOG_LEVEL})")
    client = A11yAdbClient(dev_serial=DEV_SERIAL)
    preflight = client.check_talkback_ready(dev=DEV_SERIAL)
    talkback_status = preflight.get("status", "disabled")
    talkback_reason = preflight.get("reason", "")
    log(f"[PREFLIGHT] talkback status='{talkback_status}'")
    if talkback_status == "disabled":
        log("[PREFLIGHT] abort run reason='talkback_off'")
        log("TalkBack is OFF. Enable TalkBack and retry.")
        close_log_files()
        return
    if talkback_status == "enabled_but_not_ready":
        if talkback_reason == "false_positive_enabled":
            log("[PREFLIGHT] abort run reason='false_positive_enabled'")
            log("TalkBack service is configured, but 실제 응답이 없어 실행을 중단합니다.")
        else:
            log("[PREFLIGHT] abort run reason='talkback_not_ready'")
            log("TalkBack is ON but not ready. Wait a moment and retry.")
        close_log_files()
        return

    run_perf = RunPerfStats()

    all_rows: list[dict] = []

    log(f"[MAIN] output file: {output_path}")
    log(f"[MAIN] image dir base: {output_base_dir}")

    runtime_bundle = load_runtime_bundle(TAB_CONFIGS)
    runtime_tab_configs = runtime_bundle.get("tab_configs", TAB_CONFIGS)
    checkpoint_save_every = int(runtime_bundle.get("checkpoint_save_every", 3) or 3)

    has_run_scenario = False
    try:
        for tab_cfg in runtime_tab_configs:
            if not bool(tab_cfg.get("enabled", True)):
                log(
                    f"[MAIN] skip disabled scenario_id='{tab_cfg.get('scenario_id', '')}' "
                    f"tab='{tab_cfg.get('tab_name', '')}'"
                )
                continue
            if has_run_scenario:
                recovered = recover_to_start_state(client, DEV_SERIAL, tab_cfg)
                if not recovered:
                    log(
                        f"[MAIN] recovery failed but continuing scenario_id='{tab_cfg.get('scenario_id', '')}' "
                        f"tab='{tab_cfg.get('tab_name', '')}'"
                    )
            scenario_perf = run_perf.start_scenario(
                scenario_id=str(tab_cfg.get("scenario_id", "") or ""),
                tab_name=str(tab_cfg.get("tab_name", "") or ""),
            )
            collect_tab_rows(
                client,
                DEV_SERIAL,
                tab_cfg,
                all_rows,
                output_path,
                output_base_dir,
                scenario_perf=scenario_perf,
                checkpoint_save_every=checkpoint_save_every,
            )
            has_run_scenario = True

    except Exception as exc:
        log(f"[FATAL] script interrupted: {exc}")
        run_perf.record_save_excel()
        save_excel_with_perf(save_excel, all_rows, output_path, with_images=False)
        raise

    finally:
        run_perf.record_save_excel()
        save_excel_with_perf(save_excel, all_rows, output_path, with_images=True)
        log("[MAIN] final save complete")
        log(format_perf_summary("run_summary", run_perf.summary_dict()))
        close_log_files()

    log("[MAIN] script end")


if __name__ == "__main__":
    main()
