"""Export AgenTeam roles and workflow into portable workspace-agent drafts."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import resolve_team_config
from .roles import resolve_roles
from .state import get_pipeline_stages

SCHEMA_VERSION = "1"
KIND = "agenteam.workspace_agent_export"
SENSITIVE_KEY_PARTS = ("token", "secret", "password", "credential", "api_key", "auth")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SENSITIVE_KEY_PARTS):
                result[key] = "<redacted>"
            else:
                result[key] = _redact_sensitive(item)
        return result
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _role_entry(name: str, role: dict) -> dict:
    entry = {
        "name": name,
        "description": role.get("description", ""),
        "participates_in": role.get("participates_in", []),
        "can_write": bool(role.get("can_write", False)),
        "parallel_safe": bool(role.get("parallel_safe", False)),
        "write_scope": role.get("write_scope", []),
    }
    for field in (
        "model",
        "reasoning_effort",
        "sandbox_mode",
        "nickname_candidates",
        "mcp_servers",
        "skills",
        "skills_config",
    ):
        if field in role:
            entry[field] = _redact_sensitive(role[field])
    return entry


def _stage_entry(stage: dict) -> dict:
    entry = {
        "name": stage.get("name"),
        "roles": stage.get("roles", []),
        "gate": stage.get("gate", "auto"),
    }
    for field in ("verify", "max_retries", "rework_to", "criteria"):
        if stage.get(field) not in (None, "", {}, []):
            entry[field] = stage[field]
    return entry


def _approval_points(stages: list[dict]) -> list[dict]:
    points = []
    for stage in stages:
        gate = stage.get("gate", "auto")
        if gate and gate != "auto":
            points.append(
                {
                    "stage": stage.get("name"),
                    "gate": gate,
                    "roles": stage.get("roles", []),
                    "reason": f"{gate} gate requires approval before completion",
                }
            )
    return points


def build_workspace_agent_export(config: dict) -> dict:
    """Build a compact export draft for Codex/ChatGPT workspace-agent planning."""
    pipeline_mode, isolation = resolve_team_config(config)
    stages = [_stage_entry(stage) for stage in get_pipeline_stages(config)]
    roles = resolve_roles(config)
    final_verify = config.get("final_verify", [])
    if isinstance(final_verify, str):
        final_verify = [final_verify]

    return {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "generated_at": _now_iso(),
        "target": "workspace-agent-draft",
        "source": "agenteam",
        "team": {
            "pipeline_mode": pipeline_mode or "standalone",
            "isolation": isolation,
            "role_count": len(roles),
            "stage_count": len(stages),
        },
        "roles": [_role_entry(name, roles[name]) for name in sorted(roles)],
        "workflow": {
            "stages": stages,
            "approval_points": _approval_points(stages),
            "final_verify": final_verify,
            "final_verify_policy": config.get("final_verify_policy", "block"),
        },
        "governance": {
            "run_metadata_fields": [
                "initiative",
                "phase",
                "checkpoint",
                "burn_estimate",
            ],
            "decision_log": ".agenteam/governance/decisions.jsonl",
            "tripwire_catalog": ".agenteam/governance/tripwires.yaml",
            "evidence_command": "agenteam-rt evidence --run-id <id>",
            "status_command": "agenteam-rt status <id> --progress",
        },
        "surface_guidance": {
            "codex": "Use generated .codex/agents/*.toml for repo-local specialist agents.",
            "chatgpt_workspace_agent": (
                "Use this workspace-agent draft to configure shared role purpose, "
                "allowed tools, approval points, files, and repeatable workflows."
            ),
            "slack": (
                "Use the workflow stages and approval points as routing notes for "
                "Slack-triggered tasks; keep repository writes behind Codex approval policy."
            ),
        },
        "caveats": [
            "This is a draft export, not a live Workspace Agents API import.",
            "Review redacted tool and skill settings before sharing outside the repository.",
            "Preserve repository AGENTS.md and Codex sandbox/approval policy as "
            "the source of truth.",
        ],
    }


def _render_markdown(export: dict) -> str:
    lines = [
        "# AgenTeam Workspace-Agent Draft",
        "",
        f"- Schema: `{export['kind']}` v{export['schema_version']}",
        f"- Generated: {export['generated_at']}",
        f"- Pipeline: {export['team']['pipeline_mode']}",
        f"- Isolation: {export['team']['isolation']}",
        "",
        "## Roles",
        "",
    ]

    for role in export.get("roles", []):
        lines.append(f"### {role['name']}")
        if role.get("description"):
            lines.append(role["description"])
        lines.append("")
        lines.append(f"- Participates in: {', '.join(role.get('participates_in') or []) or 'n/a'}")
        lines.append(f"- Can write: {str(role.get('can_write')).lower()}")
        if role.get("write_scope"):
            lines.append(f"- Write scope: {', '.join(role['write_scope'])}")
        if role.get("nickname_candidates"):
            lines.append(f"- Nicknames: {', '.join(role['nickname_candidates'])}")
        if role.get("mcp_servers"):
            lines.append(f"- MCP servers: {', '.join(sorted(role['mcp_servers']))}")
        lines.append("")

    lines.extend(["## Workflow", ""])
    for stage in export.get("workflow", {}).get("stages", []):
        lines.append(
            f"- **{stage['name']}**: roles `{', '.join(stage.get('roles') or [])}`, "
            f"gate `{stage.get('gate', 'auto')}`"
        )
        if stage.get("verify"):
            lines.append(f"  - Verify: `{stage['verify']}`")

    approval_points = export.get("workflow", {}).get("approval_points", [])
    if approval_points:
        lines.extend(["", "## Approval Points", ""])
        for point in approval_points:
            lines.append(f"- **{point['stage']}**: `{point['gate']}`")

    governance = export.get("governance", {})
    lines.extend(
        [
            "",
            "## Governance Evidence",
            "",
            f"- Decision log: `{governance.get('decision_log')}`",
            f"- Tripwires: `{governance.get('tripwire_catalog')}`",
            f"- Evidence: `{governance.get('evidence_command')}`",
            "",
            "## Caveats",
            "",
        ]
    )
    for caveat in export.get("caveats", []):
        lines.append(f"- {caveat}")
    return "\n".join(lines).rstrip() + "\n"


def cmd_export_workspace_agent(args, config: dict) -> None:
    """CLI handler for workspace-agent draft export."""
    export = build_workspace_agent_export(config)
    fmt = getattr(args, "format", "json")
    rendered = _render_markdown(export) if fmt == "markdown" else json.dumps(export, indent=2)

    output = getattr(args, "output", None)
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + ("" if rendered.endswith("\n") else "\n"))

    sys.stdout.write(rendered + ("" if rendered.endswith("\n") else "\n"))
