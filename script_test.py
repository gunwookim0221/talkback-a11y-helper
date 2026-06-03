import argparse
import sys
import os
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--serial", type=str, default=os.environ.get("ANDROID_SERIAL"))
parser.add_argument("--output-dir", type=str, default=None)
parser.add_argument("--mode", type=str, default="full")
parser.add_argument("--language-mode", type=str, default="current")
parser.add_argument("--launch-mode", type=str, default="warm")
parser.add_argument("--scenario", action="append", default=[])
args, _ = parser.parse_known_args()
if args.output_dir:
    os.environ["TB_OUTPUT_DIR"] = args.output_dir

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
from tb_runner.constants import LOG_LEVEL, SCRIPT_VERSION
from tb_runner.excel_report import save_excel
from tb_runner.logging_utils import close_log_files, configure_log_files, log
from tb_runner.perf_stats import RunPerfStats, format_perf_summary, save_excel_with_perf
from tb_runner.scenario_config import TAB_CONFIGS
from tb_runner.runtime_config import load_runtime_bundle
from tb_runner.core_preflight import run_preflight
from tb_runner.crash_recovery import (
    CrashRunStats,
    build_relaunch_recovery_decision,
    build_retry_outcome_decision,
    extract_crash_terminal_signal,
    render_recovery_log_lines,
    render_crash_stats_log_lines,
    resolve_crash_abort_threshold,
    run_recovery_preflight,
    should_process_crash_recovery,
    should_abort_for_crash_policy,
    update_crash_context_recovery,
    update_crash_context_batch_policy,
    update_crash_run_stats,
)
from tb_runner.run_spec import RunContext, RunSpec
from tb_runner.run_selection import apply_run_selection
from tb_runner.utils import configure_process_temp_dir, generate_output_path


def _force_utf8_stdio():
    try:
        if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


_force_utf8_stdio()


MAX_CRASH_RETRY_ATTEMPTS = 1


def _scenario_cfg_for_attempt(tab_cfg: dict, attempt: int) -> dict:
    cfg = dict(tab_cfg)
    cfg["_crash_attempt"] = max(0, int(attempt))
    return cfg


def _run_scenario_attempt(
    *,
    client: A11yAdbClient,
    target_serial: str | None,
    tab_cfg: dict,
    all_rows: list[dict],
    output_path: str,
    output_base_dir: str,
    run_perf: RunPerfStats,
    checkpoint_save_every: int,
    attempt: int,
) -> tuple[list[dict], object | None]:
    attempt_cfg = _scenario_cfg_for_attempt(tab_cfg, attempt)
    scenario_perf = run_perf.start_scenario(
        scenario_id=str(attempt_cfg.get("scenario_id", "") or ""),
        tab_name=str(attempt_cfg.get("tab_name", "") or ""),
    )
    rows = collect_tab_rows(
        client,
        target_serial,
        attempt_cfg,
        all_rows,
        output_path,
        output_base_dir,
        scenario_perf=scenario_perf,
        checkpoint_save_every=checkpoint_save_every,
    )
    signal = extract_crash_terminal_signal(getattr(client, "last_crash_terminal_signal", None)) or extract_crash_terminal_signal(rows)
    return rows, signal


def _log_crash_detected(signal) -> None:
    log(
        f"[CRASH_RECOVERY] state='CRASH_DETECTED' "
        f"scenario='{signal.scenario_id}' crash_event_id='{signal.crash_event_id}' "
        f"crash_type='{signal.crash_type}' attempt={signal.attempt}"
    )
    log(
        f"[CRASH_RECOVERY] state='ARTIFACT_CAPTURED' "
        f"scenario='{signal.scenario_id}' crash_event_id='{signal.crash_event_id}'"
    )


def main() -> int:
    spec = RunSpec(
        serial=args.serial,
        mode=args.mode,
        language_mode=args.language_mode,
        launch_mode=args.launch_mode,
        scenario_ids=tuple(args.scenario),
        output_dir=args.output_dir,
        runtime_config_path=os.environ.get("TB_RUNTIME_CONFIG_PATH"),
    )
    context = RunContext(spec)
    out_dir = context.output_dir
    temp_override_applied, temp_override_path = configure_process_temp_dir(f"{out_dir}/.tmp")
    output_path = generate_output_path()
    output_base_dir = str(Path(output_path).with_suffix(""))
    configure_log_files(output_path)
    log(
        f"[SAVE][temp] override tmp='{temp_override_path}' temp='{temp_override_path}' "
        f"applied={str(temp_override_applied).lower()}"
    )

    log(f"[MAIN] script start (version={SCRIPT_VERSION}, log_level={LOG_LEVEL})")
    target_serial = context.serial
    client = A11yAdbClient(dev_serial=target_serial)
    preflight = run_preflight(client=client, serial=target_serial, log_fn=log)
    if not preflight.ok:
        log(f"[PREFLIGHT] abort run reason='{preflight.reason}'")
    if preflight.talkback_status == "disabled":
        log("[PREFLIGHT] abort run reason='talkback_off'")
        log("TalkBack is OFF. Enable TalkBack and retry.")
        close_log_files()
        return 2
    if preflight.talkback_status == "enabled_but_not_ready":
        if preflight.talkback_reason == "false_positive_enabled":
            log("[PREFLIGHT] abort run reason='false_positive_enabled'")
            log("TalkBack service is configured, but 실제 응답이 없어 실행을 중단합니다.")
        elif preflight.talkback_reason == "external_popup_contamination":
            log("[PREFLIGHT] abort run reason='external_popup_contamination'")
            log("Google Play popup contamination remains. Return to SmartThings and retry.")
        else:
            log("[PREFLIGHT] abort run reason='talkback_not_ready'")
            log("TalkBack is ON but not ready. Wait a moment and retry.")
        close_log_files()
        return 2
    if not preflight.ok:
        close_log_files()
        return 2

    run_perf = RunPerfStats()

    all_rows: list[dict] = []

    log(f"[MAIN] output file: {output_path}")
    log(f"[MAIN] image dir base: {output_base_dir}")

    runtime_bundle = load_runtime_bundle(TAB_CONFIGS)
    runtime_tab_configs = apply_run_selection(
        runtime_bundle.get("tab_configs", TAB_CONFIGS),
        context.spec.scenario_ids,
        mode=context.spec.mode,
    )
    checkpoint_save_every = int(runtime_bundle.get("checkpoint_save_every", 3) or 3)

    has_run_scenario = False
    processed_crash_event_ids: set[str] = set()
    crash_run_stats = CrashRunStats()
    crash_abort_threshold = resolve_crash_abort_threshold()
    crash_policy_abort = False
    try:
        for tab_cfg in runtime_tab_configs:
            if crash_policy_abort:
                break
            if not bool(tab_cfg.get("enabled", True)):
                log(
                    f"[MAIN] skip disabled scenario_id='{tab_cfg.get('scenario_id', '')}' "
                    f"tab='{tab_cfg.get('tab_name', '')}'"
                )
                continue
            if has_run_scenario:
                recovered = recover_to_start_state(client, target_serial, tab_cfg)
                if not recovered:
                    log(
                        f"[MAIN] recovery failed but continuing scenario_id='{tab_cfg.get('scenario_id', '')}' "
                        f"tab='{tab_cfg.get('tab_name', '')}'"
                    )
            _rows, signal = _run_scenario_attempt(
                client=client,
                target_serial=target_serial,
                tab_cfg=tab_cfg,
                all_rows=all_rows,
                output_path=output_path,
                output_base_dir=output_base_dir,
                run_perf=run_perf,
                checkpoint_save_every=checkpoint_save_every,
                attempt=0,
            )
            if signal is not None:
                if not should_process_crash_recovery(signal, processed_crash_event_ids):
                    log(f"[CRASH_RECOVERY] duplicate_ignored crash_event_id='{signal.crash_event_id}'")
                else:
                    _log_crash_detected(signal)
                    recovery_preflight = run_recovery_preflight(client=client, serial=target_serial)
                    decision = build_relaunch_recovery_decision(
                        signal,
                        recovery_preflight,
                        attempt=signal.attempt,
                    )
                    recovery_lines = render_recovery_log_lines(decision)[2:]
                    if recovery_preflight.ok:
                        recovery_lines = [
                            line for line in recovery_lines
                            if "state='CONTINUE_WITHOUT_RETRY'" not in line
                        ]
                    for line in recovery_lines:
                        log(line)
                    if update_crash_context_recovery(signal, decision):
                        log(
                            f"[CRASH_RECOVERY] context_updated scenario='{signal.scenario_id}' "
                            f"crash_event_id='{signal.crash_event_id}' decision='{decision.decision}'"
                        )
                    if recovery_preflight.ok and signal.attempt < MAX_CRASH_RETRY_ATTEMPTS:
                        retry_attempt = signal.attempt + 1
                        log(
                            f"[CRASH_RECOVERY] state='RETRYING_SCENARIO' "
                            f"scenario='{signal.scenario_id}' crash_event_id='{signal.crash_event_id}' "
                            f"attempt={retry_attempt}"
                        )
                        _retry_rows, retry_signal = _run_scenario_attempt(
                            client=client,
                            target_serial=target_serial,
                            tab_cfg=tab_cfg,
                            all_rows=all_rows,
                            output_path=output_path,
                            output_base_dir=output_base_dir,
                            run_perf=run_perf,
                            checkpoint_save_every=checkpoint_save_every,
                            attempt=retry_attempt,
                        )
                        if retry_signal is None:
                            recovered_decision = build_retry_outcome_decision(
                                signal,
                                recovered=True,
                                attempt=retry_attempt,
                            )
                            log(
                                f"[CRASH_RECOVERY] state='CRASH_RECOVERED' "
                                f"scenario='{signal.scenario_id}' attempt={retry_attempt}"
                            )
                            update_crash_context_recovery(signal, recovered_decision)
                            update_crash_run_stats(
                                crash_run_stats,
                                signal=signal,
                                decision=recovered_decision,
                            )
                            policy = should_abort_for_crash_policy(
                                crash_run_stats,
                                threshold=crash_abort_threshold,
                                decision=recovered_decision,
                            )
                            update_crash_context_batch_policy(signal, policy)
                            for line in render_crash_stats_log_lines(
                                crash_run_stats,
                                threshold=crash_abort_threshold,
                                policy=policy,
                            ):
                                log(line)
                            if policy["decision"] == "abort":
                                crash_policy_abort = True
                        else:
                            if should_process_crash_recovery(retry_signal, processed_crash_event_ids):
                                _log_crash_detected(retry_signal)
                            repeated_decision = build_retry_outcome_decision(
                                retry_signal,
                                recovered=False,
                                attempt=retry_attempt,
                            )
                            log(
                                f"[CRASH_RECOVERY] state='CRASH_REPEATED' "
                                f"scenario='{retry_signal.scenario_id}' attempt={retry_attempt}"
                            )
                            log(
                                f"[CRASH_RECOVERY] scenario_skip "
                                f"scenario='{retry_signal.scenario_id}' reason='crash_repeated'"
                            )
                            update_crash_context_recovery(signal, repeated_decision)
                            update_crash_context_recovery(retry_signal, repeated_decision)
                            update_crash_run_stats(
                                crash_run_stats,
                                signal=signal,
                                decision=repeated_decision,
                                retry_signal=retry_signal,
                            )
                            policy = should_abort_for_crash_policy(
                                crash_run_stats,
                                threshold=crash_abort_threshold,
                                decision=repeated_decision,
                            )
                            update_crash_context_batch_policy(signal, policy)
                            update_crash_context_batch_policy(retry_signal, policy)
                            for line in render_crash_stats_log_lines(
                                crash_run_stats,
                                threshold=crash_abort_threshold,
                                policy=policy,
                            ):
                                log(line)
                            if policy["decision"] == "abort":
                                crash_policy_abort = True
                    else:
                        update_crash_run_stats(
                            crash_run_stats,
                            signal=signal,
                            decision=decision,
                        )
                        policy = should_abort_for_crash_policy(
                            crash_run_stats,
                            threshold=crash_abort_threshold,
                            decision=decision,
                        )
                        update_crash_context_batch_policy(signal, policy)
                        for line in render_crash_stats_log_lines(
                            crash_run_stats,
                            threshold=crash_abort_threshold,
                            policy=policy,
                        ):
                            log(line)
                        if policy["decision"] == "abort":
                            crash_policy_abort = True
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
