"""Prompt assembly: build the fully composed prompt for a role dispatch."""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .artifacts import resolve_artifact_paths_for_config
from .config import resolve_team_config
from .generate import build_developer_instructions
from .roles import resolve_roles

SCHEMA_VERSION = "1"


def _load_developer_instructions(role_name: str, config: dict) -> str:
    """Get developer_instructions for a role from resolved config."""
    roles = resolve_roles(config)
    role = roles.get(role_name)
    if not role:
        return ""
    return build_developer_instructions(role)


def _resolve_task(run_id: str, config: dict) -> dict:
    """Resolve the task with deterministic prior-run context."""
    from .memory import build_visible_memory

    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if not state_path.exists():
        return {"raw": "", "prior_run_context": "", "effective": ""}

    with open(state_path) as f:
        state = json.load(f)

    raw = state.get("task", "")

    # Deterministic prior-run context via build_visible_memory
    memory = build_visible_memory(config, current_run_id=run_id)
    items = memory.get("items", [])

    prior_run_context = ""
    if items:
        lines = ["## Prior Run Context", ""]
        for item in items:
            source = item.get("source_run_id", "unknown")
            kind = item.get("kind", "note")
            text = item.get("text", "")
            lines.append(f"- [{kind}] (run {source}): {text}")
        prior_run_context = "\n".join(lines)

    effective = raw
    if prior_run_context:
        effective = f"{raw}\n\n{prior_run_context}"

    return {
        "raw": raw,
        "prior_run_context": prior_run_context,
        "effective": effective,
    }


def _find_prior_artifacts(run_id: str, config: dict) -> dict:
    """Find prior-stage artifacts using best-effort mtime heuristic."""
    artifact_paths = resolve_artifact_paths_for_config(config)
    mode = "hotl" if "architect" in artifact_paths and artifact_paths.get("architect") == "docs/plans/" else "standalone"

    # Build search_paths from the artifact map
    search_paths = {}
    for key, path in artifact_paths.items():
        if isinstance(path, str):
            search_paths[key] = path
        elif isinstance(path, list):
            search_paths[key] = path[0] if path else ""

    # Best-effort: find files modified after run started_at
    selected: list[dict] = []
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)
        started_at = state.get("started_at", "")
        if started_at:
            try:
                run_start = datetime.fromisoformat(
                    started_at.replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError):
                run_start = 0

            if run_start > 0:
                kind_map = {
                    "researcher": "research",
                    "pm": "strategy",
                    "architect": "design",
                    "dev_plans": "plan",
                }
                for role_key, search_path in search_paths.items():
                    if not search_path or role_key in ("dev_code", "qa"):
                        continue
                    search_dir = Path.cwd() / search_path
                    if not search_dir.exists():
                        continue
                    for f in search_dir.iterdir():
                        if f.is_file() and f.suffix == ".md":
                            try:
                                if os.path.getmtime(f) >= run_start:
                                    selected.append({
                                        "path": str(f.relative_to(Path.cwd())),
                                        "role": role_key,
                                        "kind": kind_map.get(role_key, "artifact"),
                                    })
                            except OSError:
                                pass

    return {
        "mode": mode,
        "search_paths": search_paths,
        "selected": selected,
    }


def _build_role_context(run_id: str, stage: str, role_name: str, config: dict) -> str:
    """Build the dispatch context block for a role."""
    from .state import resolve_stages_for_run

    roles = resolve_roles(config)
    role = roles.get(role_name, {})
    _, isolation_mode = resolve_team_config(config)

    # Stage info
    stages = resolve_stages_for_run(run_id, config)
    stage_config = None
    for s in stages:
        if s["name"] == stage:
            stage_config = s
            break

    gate = stage_config.get("gate", "auto") if stage_config else "auto"
    verify = stage_config.get("verify", "") if stage_config else ""

    # Handoff
    handoff = role.get("handoff_contract", {})

    lines = [
        "## AgenTeam Dispatch Context",
        "",
        f"**Stage:** {stage}",
        f"**Role:** {role_name}",
        f"**Policy:** {isolation_mode}",
        f"**Gate:** {gate}",
    ]
    if verify:
        lines.append(f"**Verify Command:** {verify}")
    if handoff:
        if handoff.get("passes_to"):
            lines.append(f"**Your Output Goes To:** {handoff['passes_to']}")

    return "\n".join(lines)


def _resolve_hotl(run_id: str, stage: str, role_name: str, config: dict) -> dict:
    """Check HOTL skill eligibility — graceful if unavailable."""
    try:
        from .hotl_adapter import resolve_eligible_skills

        result = resolve_eligible_skills(run_id, stage, role_name, config)
        return {
            "available": result.get("hotl_available", False),
            "eligible": result.get("eligible", []),
        }
    except Exception:
        return {"available": False, "eligible": []}


def build_prompt(run_id: str, stage: str, role_name: str, config: dict) -> dict:
    """Build the fully composed prompt for a role dispatch.

    Returns a structured dict with schema_version, components, and
    the composed prompt string.
    """
    # Developer instructions from resolved role config
    dev_instructions = _load_developer_instructions(role_name, config)

    # Task with deterministic prior-run context
    task = _resolve_task(run_id, config)

    # Prior artifacts (best-effort)
    artifacts = _find_prior_artifacts(run_id, config)

    # Role context (dispatch info)
    role_context = _build_role_context(run_id, stage, role_name, config)

    # HOTL skill eligibility
    hotl = _resolve_hotl(run_id, stage, role_name, config)

    # Handoff contract from resolved role
    roles = resolve_roles(config)
    role = roles.get(role_name, {})
    handoff = role.get("handoff_contract", {})

    # Verification info from stage config
    from .state import resolve_stages_for_run

    stages = resolve_stages_for_run(run_id, config)
    stage_config = None
    for s in stages:
        if s["name"] == stage:
            stage_config = s
            break

    verification: dict = {}
    if stage_config:
        verify_cmd = stage_config.get("verify", "")
        if verify_cmd:
            verification = {
                "command": verify_cmd,
                "source": "config",
                "max_retries": stage_config.get("max_retries", 0),
                "cwd": str(Path.cwd()),
            }

    # Dispatch context
    _, isolation_mode = resolve_team_config(config)
    dispatch_context = {
        "policy": isolation_mode,
        "gate": stage_config.get("gate", "auto") if stage_config else "auto",
        "mode": "write" if role.get("can_write") else "read",
    }

    # Build prior_artifacts text
    artifact_text = ""
    if artifacts["selected"]:
        lines = ["## Prior Stage Artifacts", ""]
        for a in artifacts["selected"]:
            lines.append(f"- {a['role']}: {a['path']} ({a['kind']})")
        artifact_text = "\n".join(lines)

    # HOTL injection text
    hotl_text = ""
    if hotl["eligible"]:
        lines = []
        for e in hotl["eligible"]:
            lines.append(e.get("inject", ""))
        hotl_text = "\n".join(lines)

    # Assemble prompt_sections
    prompt_sections = [
        {"id": "developer_instructions", "text": dev_instructions},
        {"id": "task", "text": task["effective"]},
    ]
    if artifact_text:
        prompt_sections.append({"id": "prior_artifacts", "text": artifact_text})
    prompt_sections.append({"id": "role_context", "text": role_context})
    if hotl_text:
        prompt_sections.append({"id": "hotl_injection", "text": hotl_text})

    # Compose prompt
    prompt = "\n\n".join(s["text"] for s in prompt_sections if s["text"])

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "stage": stage,
        "role": role_name,
        "agent": {
            "toml_path": f".codex/agents/{role_name}.toml",
            "developer_instructions": dev_instructions,
        },
        "task": task,
        "handoff_contract": {
            "produces": handoff.get("produces", ""),
            "expects": handoff.get("expects", ""),
            "passes_to": handoff.get("passes_to", ""),
        },
        "verification": verification,
        "artifacts": artifacts,
        "hotl": hotl,
        "dispatch_context": dispatch_context,
        "prompt_sections": prompt_sections,
        "prompt": prompt,
    }


def cmd_prompt_build(args, config: dict) -> None:
    """CLI handler for: agenteam-rt prompt-build."""
    result = build_prompt(args.run_id, args.stage, args.role, config)
    print(json.dumps(result, indent=2))
