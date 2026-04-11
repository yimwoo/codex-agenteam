"""TOML agent generation from resolved roles."""

import json
from pathlib import Path

import toml

from .roles import resolve_roles


def build_developer_instructions(role: dict) -> str:
    """Build the developer_instructions string from a resolved role.

    This is the canonical prompt for a role, used by both TOML generation
    and prompt-build.
    """
    instructions_parts = []
    if "system_instructions" in role:
        instructions_parts.append(role["system_instructions"].rstrip())

    # Append role metadata
    metadata_lines = []
    if "participates_in" in role:
        metadata_lines.append(f"participates_in: {', '.join(role['participates_in'])}")
    if "can_write" in role:
        metadata_lines.append(f"can_write: {str(role['can_write']).lower()}")
    if "parallel_safe" in role:
        metadata_lines.append(f"parallel_safe: {str(role['parallel_safe']).lower()}")

    if metadata_lines:
        instructions_parts.append("\n## Role Metadata\n" + "\n".join(metadata_lines))

    # Append handoff contract if present
    handoff = role.get("handoff_contract") or {}
    if handoff:
        handoff_lines = []
        if "produces" in handoff:
            handoff_lines.append(f"produces: {handoff['produces']}")
        if "expects" in handoff:
            handoff_lines.append(f"expects: {handoff['expects']}")
        if "passes_to" in handoff:
            handoff_lines.append(f"passes_to: {handoff['passes_to']}")
        if handoff_lines:
            instructions_parts.append("\n## Handoff Contract\n" + "\n".join(handoff_lines))

    return "\n".join(instructions_parts)


def generate_agent_toml(role: dict) -> str:
    """Generate Codex agent TOML from a resolved role."""
    agent = {}
    agent["name"] = role["name"]
    agent["description"] = role.get("description", "").strip()

    # Optional config fields
    if "model" in role:
        agent["model"] = role["model"]
    if "reasoning_effort" in role:
        agent["model_reasoning_effort"] = role["reasoning_effort"]
    if "sandbox_mode" in role:
        agent["sandbox_mode"] = role["sandbox_mode"]

    agent["developer_instructions"] = build_developer_instructions(role)

    result: str = toml.dumps(agent)
    return result


def cmd_generate(args, config: dict) -> None:
    """Generate .codex/agents/*.toml for all resolved roles."""
    roles = resolve_roles(config)
    agents_dir = Path.cwd() / ".codex" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    for name, role in sorted(roles.items()):
        toml_content = generate_agent_toml(role)
        out_path = agents_dir / f"{name}.toml"
        with open(out_path, "w") as f:
            f.write(toml_content)
        generated.append(str(out_path))

    result = {"generated": generated}

    count = len(generated)
    warnings = []
    if count > 6:
        warnings.append(
            f"You have {count} agents. Codex defaults to 6 concurrent threads. "
            "Set agents.max_threads in your Codex config.toml to run more in parallel."
        )
    if count > 12:
        warnings.append(
            f"You have {count} agents. Teams above 12 can increase coordination "
            "overhead. Consider consolidating roles with overlapping responsibilities."
        )
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result))
