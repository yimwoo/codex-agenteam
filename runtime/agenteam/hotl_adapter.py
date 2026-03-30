"""HOTL execution-skill adapter: eligibility resolution for role-level skill hooks."""

import json
from pathlib import Path

from .hotl import hotl_available
from .roles import resolve_roles

# Fixed mapping from AgenTeam config keys to HOTL skill invocation names.
HOTL_SKILL_MAP: dict[str, str] = {
    "tdd": "hotl:tdd",
    "systematic-debugging": "hotl:systematic-debugging",
    "code-review": "hotl:code-review",
}

# Injection text for each skill when eligible.
INJECT_TEXT: dict[str, str] = {
    "tdd": (
        "Use TDD workflow: invoke the hotl:tdd skill"
        " before writing implementation code."
    ),
    "systematic-debugging": (
        "Use systematic debugging: invoke the"
        " hotl:systematic-debugging skill"
        " before proposing fixes."
    ),
    "code-review": (
        "Use HOTL code review: invoke the"
        " hotl:code-review skill for structured review."
    ),
}


def _get_stage_status(run_id: str, stage_name: str) -> str | None:
    """Load stage status from state file. Returns None if unavailable."""
    state_path = Path.cwd() / ".agenteam" / "state" / f"{run_id}.json"
    if not state_path.exists():
        return None
    try:
        with open(state_path) as f:
            state = json.load(f)
        return state.get("stages", {}).get(stage_name, {}).get("status")
    except (json.JSONDecodeError, OSError):
        return None


def _check_eligibility(
    skill: str,
    role_name: str,
    stage_name: str,
    stage_status: str | None,
) -> tuple[bool, str]:
    """Check if a skill is eligible given role, stage, and stage status.

    Returns (eligible, reason).
    """
    if skill == "tdd":
        if role_name == "dev" and stage_name == "implement":
            return True, "role is dev, stage is implement"
        return False, (
            f"requires role=dev and stage=implement"
            f" (got role={role_name},"
            f" stage={stage_name})"
        )

    if skill == "systematic-debugging":
        if role_name == "dev" and stage_status in ("failed", "rework"):
            return True, f"role is dev, stage status is {stage_status}"
        return False, (
            f"requires role=dev and stage status"
            f" failed/rework (got role={role_name},"
            f" status={stage_status})"
        )

    if skill == "code-review":
        if role_name == "reviewer" and stage_name == "review":
            return True, "role is reviewer, stage is review"
        return False, (
            f"requires role=reviewer and stage=review"
            f" (got role={role_name},"
            f" stage={stage_name})"
        )

    return False, f"unknown skill '{skill}'"


def resolve_eligible_skills(
    run_id: str,
    stage_name: str,
    role_name: str,
    config: dict,
) -> dict:
    """Resolve HOTL skill eligibility for a role in a stage.

    Returns the full eligibility result dict.
    """
    hotl_info = hotl_available()
    hotl_is_available = hotl_info["available"]
    hotl_path = hotl_info.get("path", "")

    # Get configured hotl_skills for the role
    roles = resolve_roles(config)
    role_config = roles.get(role_name, {})
    configured_skills = role_config.get("hotl_skills", [])

    # Filter to known skills
    configured_skills = [s for s in configured_skills if s in HOTL_SKILL_MAP]

    # Get stage status for eligibility checks
    stage_status = _get_stage_status(run_id, stage_name)

    eligible: list[dict] = []
    not_eligible: list[dict] = []

    for skill in configured_skills:
        is_eligible, reason = _check_eligibility(skill, role_name, stage_name, stage_status)
        if is_eligible:
            eligible.append({
                "skill": skill,
                "hotl_skill": HOTL_SKILL_MAP[skill],
                "inject": INJECT_TEXT[skill],
            })
        else:
            not_eligible.append({
                "skill": skill,
                "hotl_skill": HOTL_SKILL_MAP[skill],
                "reason": reason,
            })

    return {
        "hotl_available": hotl_is_available,
        "hotl_path": hotl_path,
        "role": role_name,
        "stage": stage_name,
        "configured_skills": configured_skills,
        "eligible": eligible,
        "not_eligible": not_eligible,
    }


def cmd_hotl_skills(args, config: dict) -> None:
    """CLI handler for: agenteam-rt hotl-skills."""
    result = resolve_eligible_skills(args.run_id, args.stage, args.role, config)
    print(json.dumps(result))
