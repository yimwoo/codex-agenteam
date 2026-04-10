"""CLI parser and main entry point for the AgenTeam runtime."""

import argparse
import json
import sys

import yaml

from .artifacts import cmd_artifact_paths
from .branch import cmd_branch_plan
from .config import find_config, load_config, load_config_merged_raw
from .dispatch import (
    cmd_dispatch,
    cmd_policy_check,
    cmd_roles_list,
    cmd_roles_show,
    cmd_scope_audit,
)
from .events import cmd_event_append, cmd_event_list, cmd_event_tail
from .gates import cmd_gate_eval
from .generate import cmd_generate
from .hotl import cmd_health, cmd_hotl_check
from .hotl_adapter import cmd_hotl_skills
from .migrate import cmd_migrate
from .report import cmd_history_append, cmd_history_list, cmd_run_report
from .resume import cmd_resume_detect, cmd_resume_plan
from .standup import cmd_standup
from .state import cmd_init, cmd_stage_baseline, cmd_status, set_stage_field, validate_run_id
from .transitions import cmd_transition
from .validate import cmd_validate
from .verify import cmd_final_verify_plan, cmd_record_gate, cmd_record_verify, cmd_verify_plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenteam-rt",
        description="AgenTeam (codex-agenteam) runtime engine",
    )
    parser.add_argument("--config", help="Path to agenteam.yaml")

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize a run")
    p_init.add_argument("--task", required=False, default="unnamed task")
    p_init.add_argument("--profile", required=False, default=None)

    # generate
    sub.add_parser("generate", help="Generate .codex/agents/*.toml")

    # validate
    p_validate = sub.add_parser("validate", help="Validate config without creating run state")
    p_validate.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="Treat warnings as errors (exit 1 on warnings)",
    )
    p_validate.add_argument(
        "--format",
        choices=["summary", "diagnostics"],
        default="summary",
        help="Output format: summary or diagnostics (full structured)",
    )

    # migrate
    p_migrate = sub.add_parser("migrate", help="Migrate legacy config to canonical format")
    p_migrate.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Show what would change without writing files",
    )

    # dispatch
    p_dispatch = sub.add_parser("dispatch", help="Generate dispatch plan for a stage")
    p_dispatch.add_argument("stage", help="Stage name")
    p_dispatch.add_argument("--task", default="")
    p_dispatch.add_argument("--run-id", dest="run_id", default=None)

    # status
    p_status = sub.add_parser("status", help="Show run status")
    p_status.add_argument("run_id", nargs="?", default=None)
    p_status.add_argument("--progress", action="store_true", default=False, help="Compact progress view")

    # policy
    p_policy = sub.add_parser("policy", help="Policy commands")
    p_policy_sub = p_policy.add_subparsers(dest="policy_cmd")
    p_policy_sub.add_parser("check", help="Check write scope overlaps")

    # roles
    p_roles = sub.add_parser("roles", help="Role commands")
    p_roles_sub = p_roles.add_subparsers(dest="roles_cmd")
    p_roles_sub.add_parser("list", help="List all resolved roles")
    p_show = p_roles_sub.add_parser("show", help="Show a specific role")
    p_show.add_argument("name", help="Role name")

    # hotl
    p_hotl = sub.add_parser("hotl", help="HOTL integration")
    p_hotl_sub = p_hotl.add_subparsers(dest="hotl_cmd")
    p_hotl_sub.add_parser("check", help="Check HOTL availability")

    # health
    sub.add_parser("health", help="Show minimal runtime/project readiness")

    # artifact-paths
    sub.add_parser("artifact-paths", help="Show artifact output paths (auto-detects HOTL)")

    # branch-plan
    p_branch = sub.add_parser("branch-plan", help="Resolve branch/worktree plan for a task")
    p_branch.add_argument("--task", required=True, help="Task description")
    p_branch.add_argument("--run-id", dest="run_id", default=None, help="Run ID (pipeline context)")
    p_branch.add_argument("--role", default=None, help="Role name (assign context)")

    # standup
    p_standup = sub.add_parser("standup", help="Assemble standup summary")
    p_standup.add_argument(
        "--task", required=False, default=None, help="Optional task context for the standup"
    )
    p_standup.add_argument(
        "--dispatch",
        action="store_true",
        default=False,
        help="Include dispatch_mode=true for deepdive skill",
    )

    # scope-audit
    p_scope_audit = sub.add_parser("scope-audit", help="Audit changed files against write_scopes")
    p_scope_audit.add_argument("--run-id", dest="run_id", default=None)
    p_scope_audit.add_argument("--stage", required=True, help="Stage name")
    p_scope_audit.add_argument("--baseline", required=True, help="Baseline commit SHA")

    # verify-plan
    p_verify_plan = sub.add_parser("verify-plan", help="Get verification plan for a stage")
    p_verify_plan.add_argument("stage", help="Stage name")
    p_verify_plan.add_argument("--run-id", dest="run_id", default=None)

    # record-verify
    p_record_verify = sub.add_parser("record-verify", help="Record a verification result")
    p_record_verify.add_argument("--run-id", dest="run_id", required=True)
    p_record_verify.add_argument("--stage", required=True)
    p_record_verify.add_argument("--result", required=True, choices=["pass", "fail"])
    p_record_verify.add_argument("--output", default="")

    # final-verify-plan
    p_final_verify = sub.add_parser("final-verify-plan", help="Get final verification plan")
    p_final_verify.add_argument("--run-id", dest="run_id", default=None)

    # record-gate
    p_record_gate = sub.add_parser("record-gate", help="Record a gate decision")
    p_record_gate.add_argument("--run-id", dest="run_id", required=True)
    p_record_gate.add_argument("--stage", required=True)
    p_record_gate.add_argument("--gate-type", dest="gate_type", required=True)
    p_record_gate.add_argument("--result", required=True, choices=["approved", "rejected"])
    p_record_gate.add_argument("--verdict", default="")
    p_record_gate.add_argument("--criteria-failed", dest="criteria_failed", default="")
    p_record_gate.add_argument("--criteria-details", dest="criteria_details", default="")
    p_record_gate.add_argument("--override-reason", dest="override_reason", default="")

    # record-verify: add --rework-stage
    p_record_verify.add_argument("--rework-stage", dest="rework_stage", default=None)

    # stage-baseline
    p_stage_baseline = sub.add_parser("stage-baseline", help="Capture or rollback a stage baseline")
    p_stage_baseline.add_argument("--run-id", dest="run_id", required=True)
    p_stage_baseline.add_argument("--stage", required=True)
    p_stage_baseline.add_argument("--action", required=True, choices=["capture", "rollback"])

    # set-stage-field
    p_ssf = sub.add_parser("set-stage-field", help="Set an arbitrary field on a stage in state")
    p_ssf.add_argument("--run-id", dest="run_id", required=True)
    p_ssf.add_argument("--stage", required=True)
    p_ssf.add_argument("--field", required=True)
    p_ssf.add_argument("--value", required=True)

    # run-report
    p_run_report = sub.add_parser("run-report", help="Assemble run report from state")
    p_run_report.add_argument("--run-id", dest="run_id", required=True)

    # gate-eval
    p_gate_eval = sub.add_parser("gate-eval", help="Evaluate gate criteria for a stage")
    p_gate_eval.add_argument("--run-id", dest="run_id", required=True)
    p_gate_eval.add_argument("--stage", required=True)

    # hotl-skills
    p_hotl_skills = sub.add_parser("hotl-skills", help="Resolve HOTL skill eligibility")
    p_hotl_skills.add_argument("--run-id", dest="run_id", required=True)
    p_hotl_skills.add_argument("--stage", required=True)
    p_hotl_skills.add_argument("--role", required=True)

    # resume-detect
    sub.add_parser("resume-detect", help="Scan for stale resumable runs")

    # resume-plan
    p_resume_plan = sub.add_parser("resume-plan", help="Build structured resume plan")
    p_resume_plan.add_argument("--run-id", dest="run_id", required=True)

    # transition
    p_transition = sub.add_parser("transition", help="Validate and apply a stage status transition")
    p_transition.add_argument("--run-id", dest="run_id", required=True)
    p_transition.add_argument("--stage", required=True)
    p_transition.add_argument("--to", required=True)

    # event
    p_event = sub.add_parser("event", help="Event log commands")
    p_event_sub = p_event.add_subparsers(dest="event_cmd")
    p_event_append = p_event_sub.add_parser("append", help="Append an event")
    p_event_append.add_argument("--run-id", dest="run_id", required=True)
    p_event_append.add_argument("--type", required=True)
    p_event_append.add_argument("--stage", default=None)
    p_event_append.add_argument("--data", default="{}")
    p_event_list = p_event_sub.add_parser("list", help="List events")
    p_event_list.add_argument("--run-id", dest="run_id", required=True)
    p_event_list.add_argument("--type", default=None)
    p_event_list.add_argument("--stage", default=None)
    p_event_list.add_argument("--last", type=int, default=None)
    p_event_tail = p_event_sub.add_parser("tail", help="Stream events as they're appended")
    p_event_tail.add_argument("--run-id", dest="run_id", required=True)

    # history
    p_history = sub.add_parser("history", help="Run history commands")
    p_history_sub = p_history.add_subparsers(dest="history_cmd")
    p_history_append = p_history_sub.add_parser("append", help="Persist run summary + lessons")
    p_history_append.add_argument("--run-id", dest="run_id", required=True)
    p_history_list = p_history_sub.add_parser("list", help="List recent history entries")
    p_history_list.add_argument("--last", type=int, default=10)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    # HOTL check doesn't need config
    if args.command == "hotl":
        if args.hotl_cmd == "check":
            cmd_hotl_check(args)
        else:
            print(json.dumps({"error": "Unknown hotl subcommand"}), file=sys.stderr)
            sys.exit(1)
        return

    if args.command == "resume-detect":
        cmd_resume_detect(args)
        return

    if args.command == "event":
        if args.event_cmd == "append":
            cmd_event_append(args)
        elif args.event_cmd == "list":
            cmd_event_list(args)
        elif args.event_cmd == "tail":
            cmd_event_tail(args)
        else:
            print(json.dumps({"error": "Unknown event subcommand"}), file=sys.stderr)
            sys.exit(1)
        return

    if args.command == "history":
        if args.history_cmd == "append":
            cmd_history_append(args)
        elif args.history_cmd == "list":
            cmd_history_list(args)
        else:
            print(json.dumps({"error": "Unknown history subcommand"}), file=sys.stderr)
            sys.exit(1)
        return

    if args.command == "health":
        try:
            cmd_health(args)
        except (ValueError, json.JSONDecodeError, OSError, yaml.YAMLError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
        return

    # migrate handles its own config loading (raw, no validation)
    if args.command == "migrate":
        cmd_migrate(args)
        return

    # validate loads merged config raw so it reports against effective config
    if args.command == "validate":
        try:
            cfg_arg = args.config if hasattr(args, "config") and args.config else None
            config_path = find_config(cfg_arg)
            config = load_config_merged_raw(config_path)
        except (FileNotFoundError, ValueError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
        cmd_validate(args, config)
        return

    # All other commands need config
    try:
        cfg_arg = args.config if hasattr(args, "config") and args.config else None
        config_path = find_config(cfg_arg)
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    # Validate run_id if present (prevent path traversal)
    run_id = getattr(args, "run_id", None)
    if run_id:
        try:
            validate_run_id(run_id)
        except ValueError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    if args.command == "branch-plan":
        cmd_branch_plan(args, config)
    elif args.command == "standup":
        cmd_standup(args, config)
    elif args.command == "artifact-paths":
        cmd_artifact_paths(args, config)
    elif args.command == "init":
        cmd_init(args, config)
    elif args.command == "generate":
        cmd_generate(args, config)
    elif args.command == "dispatch":
        cmd_dispatch(args, config)
    elif args.command == "scope-audit":
        cmd_scope_audit(args, config)
    elif args.command == "status":
        cmd_status(args, config)
    elif args.command == "policy":
        if args.policy_cmd == "check":
            cmd_policy_check(args, config)
        else:
            print(json.dumps({"error": "Unknown policy subcommand"}), file=sys.stderr)
            sys.exit(1)
    elif args.command == "roles":
        if args.roles_cmd == "list":
            cmd_roles_list(args, config)
        elif args.roles_cmd == "show":
            cmd_roles_show(args, config)
        else:
            print(json.dumps({"error": "Unknown roles subcommand"}), file=sys.stderr)
            sys.exit(1)
    elif args.command == "verify-plan":
        cmd_verify_plan(args, config)
    elif args.command == "record-verify":
        cmd_record_verify(args, config)
    elif args.command == "final-verify-plan":
        cmd_final_verify_plan(args, config)
    elif args.command == "record-gate":
        cmd_record_gate(args, config)
    elif args.command == "stage-baseline":
        cmd_stage_baseline(args, config)
    elif args.command == "set-stage-field":
        set_stage_field(args.run_id, args.stage, args.field, args.value)
        print(json.dumps({"updated": True, "stage": args.stage, "field": args.field}))
    elif args.command == "run-report":
        cmd_run_report(args, config)
    elif args.command == "gate-eval":
        cmd_gate_eval(args, config)
    elif args.command == "transition":
        cmd_transition(args, config)
    elif args.command == "resume-plan":
        cmd_resume_plan(args, config)
    elif args.command == "hotl-skills":
        cmd_hotl_skills(args, config)
    else:
        parser.print_help()
        sys.exit(1)
