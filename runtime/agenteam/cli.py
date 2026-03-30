"""CLI parser and main entry point for the AgenTeam runtime."""

import argparse
import json
import sys

import yaml

from .artifacts import cmd_artifact_paths
from .branch import cmd_branch_plan
from .config import find_config, load_config
from .dispatch import cmd_dispatch, cmd_policy_check, cmd_roles_list, cmd_roles_show
from .generate import cmd_generate
from .hotl import cmd_health, cmd_hotl_check
from .standup import cmd_standup
from .state import cmd_init, cmd_status


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

    # generate
    sub.add_parser("generate", help="Generate .codex/agents/*.toml")

    # dispatch
    p_dispatch = sub.add_parser("dispatch", help="Generate dispatch plan for a stage")
    p_dispatch.add_argument("stage", help="Stage name")
    p_dispatch.add_argument("--task", default="")
    p_dispatch.add_argument("--run-id", dest="run_id", default=None)

    # status
    p_status = sub.add_parser("status", help="Show run status")
    p_status.add_argument("run_id", nargs="?", default=None)

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

    if args.command == "health":
        try:
            cmd_health(args)
        except (ValueError, json.JSONDecodeError, OSError, yaml.YAMLError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
        return

    # All other commands need config
    try:
        config_path = find_config(args.config if hasattr(args, "config") and args.config else None)
        config = load_config(config_path)
    except (FileNotFoundError, ValueError) as e:
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
    else:
        parser.print_help()
        sys.exit(1)
