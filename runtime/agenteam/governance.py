"""Governed delivery foundations: bootstrap assets and decision logging."""

import json
import re
import sys
import time
from pathlib import Path

import yaml

from .config import resolve_project_root

DECISION_OUTCOMES = {
    "autonomous",
    "escalated",
    "blocked",
    "overridden",
    "rejected",
    "deferred",
}

HUMAN_DISPOSITIONS = {
    "agree",
    "disagree",
    "needs-followup",
}
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
OPEN_DECISION_OUTCOMES = {"escalated", "blocked", "rejected", "deferred"}


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _project_root(args=None) -> Path:
    config_arg = getattr(args, "config", None) if args is not None else None
    if not config_arg:
        return Path.cwd()

    path = Path(config_arg)
    if path.is_file():
        return resolve_project_root(path.resolve())
    if path.is_dir():
        return path.resolve()
    raise FileNotFoundError(f"Config path does not exist: {path}")


def _governance_root(args=None) -> Path:
    return _project_root(args) / ".agenteam" / "governance"


def _decisions_jsonl_path(args=None) -> Path:
    return _governance_root(args) / "decisions.jsonl"


def _decision_log_markdown_path(args=None) -> Path:
    return _project_root(args) / "docs" / "decisions" / "log.md"


def _tripwires_config_path(args=None) -> Path:
    return _governance_root(args) / "tripwires.yaml"


def _state_path(run_id: str, args=None) -> Path:
    return _project_root(args) / ".agenteam" / "state" / f"{run_id}.json"


def _write_if_missing(path: Path, content: str) -> bool:
    if path.exists():
        return False
    _ensure_parent(path)
    with open(path, "w") as f:
        f.write(content)
    return True


def cmd_governed_bootstrap(args, config: dict | None = None) -> None:
    """Scaffold local governed-delivery files for the current repository."""
    created: list[str] = []
    try:
        governance_root = _governance_root(args)
        decision_log_path = _decision_log_markdown_path(args)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    operating_model = """# Governed Delivery Operating Model (Local)

preset: standard
phase_rhythm:
  - kickoff-review
  - requirements
  - triage
  - adrs
  - brainstorm
  - plan
  - plan-review
  - execution
  - exit-gate
checkpoint_types:
  - strategic
  - kickoff
  - digest
  - exit
"""
    if _write_if_missing(governance_root / "operating-model.yaml", operating_model):
        created.append(".agenteam/governance/operating-model.yaml")

    tripwires = """# Tripwire catalog selection (local defaults)
tripwires:
  - id: public-api-change
    severity: warn
    path_glob: "src/api/**"
    message: "Public API change detected. Confirm review and compatibility notes."
  - id: dependency-addition
    severity: warn
    path_glob: "pyproject.toml"
    message: "Dependency change detected. Confirm rationale and downstream impact."
  - id: auth-surface-change
    severity: block
    path_glob: "src/auth/**"
    message: "Auth-sensitive change detected. Security review is required."
  - id: adr-required
    severity: warn
    artifact_type: adr
    decision_right: schema-change
    message: "Schema-impacting decision recorded. Confirm ADR linkage."
"""
    if _write_if_missing(governance_root / "tripwires.yaml", tripwires):
        created.append(".agenteam/governance/tripwires.yaml")

    lifecycle = """{
  "initiatives": [],
  "updated_at": null
}
"""
    if _write_if_missing(governance_root / "lifecycle.json", lifecycle):
        created.append(".agenteam/governance/lifecycle.json")

    playbook_readme = """# Playbooks

Add project or initiative playbooks here.
Each playbook maps phase sessions to role + skill + expected artifact.
"""
    if _write_if_missing(governance_root / "playbooks" / "README.md", playbook_readme):
        created.append(".agenteam/governance/playbooks/README.md")

    decision_log = """# Decision Log

Append-only rendered decision log from `.agenteam/governance/decisions.jsonl`.
Regenerate with:

```
agenteam-rt decision render-log
```
"""
    if _write_if_missing(decision_log_path, decision_log):
        created.append("docs/decisions/log.md")

    decisions_jsonl = _decisions_jsonl_path(args)
    if not decisions_jsonl.exists():
        _ensure_parent(decisions_jsonl)
        decisions_jsonl.touch()
        created.append(".agenteam/governance/decisions.jsonl")

    print(
        json.dumps(
            {
                "ok": True,
                "created": created,
                "governance_root": str(governance_root),
            }
        )
    )


def _read_decisions_from_path(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows: list[dict] = []
    with open(path) as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"Malformed decision log at line {lineno}: {e.msg}") from e
    return rows


def _read_decisions(args=None) -> list[dict]:
    return _read_decisions_from_path(_decisions_jsonl_path(args))


def _load_tripwires_from_path(path: Path) -> list[dict]:
    if not path.exists():
        return []

    with open(path) as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise ValueError(f"Malformed tripwires config: {e}") from e

    if not isinstance(raw, dict):
        raise ValueError("Malformed tripwires config: root must be a mapping")

    tripwires = raw.get("tripwires", [])
    if not isinstance(tripwires, list):
        raise ValueError("Malformed tripwires config: 'tripwires' must be a list")

    normalized: list[dict] = []
    for idx, item in enumerate(tripwires, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Malformed tripwires config: entry {idx} must be a mapping")

        tripwire_id = item.get("id")
        severity = item.get("severity", "warn")
        if not isinstance(tripwire_id, str) or not tripwire_id.strip():
            raise ValueError(f"Malformed tripwires config: entry {idx} missing non-empty 'id'")
        if severity not in {"warn", "block"}:
            raise ValueError(
                f"Malformed tripwires config: entry {idx} has invalid severity '{severity}'"
            )

        normalized.append(
            {
                "id": tripwire_id,
                "severity": severity,
                "path_glob": item.get("path_glob"),
                "artifact_type": item.get("artifact_type"),
                "decision_right": item.get("decision_right"),
                "message": item.get("message", ""),
            }
        )

    return normalized


def _load_tripwires(args=None) -> list[dict]:
    return _load_tripwires_from_path(_tripwires_config_path(args))


def _tripwire_matches(
    tripwire: dict, paths: list[str], artifact_type: str | None, decision_right: str | None
) -> bool:
    path_glob = tripwire.get("path_glob")
    if path_glob:
        if not any(Path(path).match(path_glob) for path in paths):
            return False

    expected_artifact_type = tripwire.get("artifact_type")
    if expected_artifact_type and artifact_type != expected_artifact_type:
        return False

    expected_decision_right = tripwire.get("decision_right")
    if expected_decision_right and decision_right != expected_decision_right:
        return False

    return True


def _load_state_for_governance(run_id: str, args=None) -> tuple[Path, dict]:
    if not _RUN_ID_RE.match(run_id):
        raise ValueError(
            f"Invalid --run-id '{run_id}'. "
            "Must contain only alphanumeric characters, hyphens, and underscores."
        )
    path = _state_path(run_id, args)
    if not path.exists():
        raise FileNotFoundError(f"Run {run_id} not found")
    with open(path) as f:
        return path, json.load(f)


def _compact_decision(row: dict) -> dict:
    fields = (
        "id",
        "ts",
        "outcome",
        "summary",
        "role",
        "stage",
        "artifact_type",
        "artifact_ref",
        "decision_right",
        "tripwire_id",
        "human_disposition",
    )
    return {field: row[field] for field in fields if row.get(field) not in (None, "")}


def _compact_tripwire_check(row: dict) -> dict:
    fields = (
        "ts",
        "stage",
        "passed",
        "warn",
        "block",
        "paths",
        "artifact_type",
        "decision_right",
        "matched",
    )
    return {field: row[field] for field in fields if row.get(field) not in (None, "", [])}


def _stage_gate_summaries(state: dict) -> tuple[list[dict], list[dict], list[dict]]:
    rejections: list[dict] = []
    blocks: list[dict] = []
    overrides: list[dict] = []
    for stage_name, stage_state in state.get("stages", {}).items():
        gate_result = stage_state.get("gate_result")
        if gate_result == "rejected":
            entry = {
                "stage": stage_name,
                "gate_type": stage_state.get("gate", "unknown"),
            }
            if stage_state.get("gate_verdict"):
                entry["verdict"] = stage_state["gate_verdict"]
            rejections.append(entry)
        elif gate_result == "blocked":
            entry = {
                "stage": stage_name,
                "gate_type": stage_state.get("gate", "unknown"),
            }
            if stage_state.get("gate_agent"):
                entry["agent"] = stage_state["gate_agent"]
            blocks.append(entry)

        if stage_state.get("gate_type") == "criteria_override":
            entry = {
                "stage": stage_name,
                "criteria_failed": stage_state.get("criteria_failed", []),
                "override_reason": stage_state.get("override_reason", ""),
            }
            if stage_state.get("criteria_details"):
                entry["criteria_details"] = stage_state["criteria_details"]
            overrides.append(entry)

    return rejections, blocks, overrides


def _legacy_governance_metadata(state: dict) -> dict:
    governance = state.get("governance")
    metadata = dict(governance) if isinstance(governance, dict) else {}
    metadata.pop("adoption", None)
    metadata.pop("tripwire_checks", None)

    for key in (
        "initiative",
        "phase",
        "checkpoint",
        "burn_estimate",
        "escalation_status",
    ):
        if key not in metadata and state.get(key) is not None:
            metadata[key] = state[key]
    return metadata


def build_governance_adoption(
    run_id: str, state: dict, project_root: Path | None = None
) -> dict | None:
    """Build a compact governed-delivery adoption summary for status/evidence views."""
    root = project_root or Path.cwd()
    governance = state.get("governance")
    tripwire_checks = governance.get("tripwire_checks", []) if isinstance(governance, dict) else []
    if not isinstance(tripwire_checks, list):
        tripwire_checks = []

    errors: list[str] = []
    try:
        decisions = [
            row
            for row in _read_decisions_from_path(
                root / ".agenteam" / "governance" / "decisions.jsonl"
            )
            if row.get("run_id") == run_id
        ]
    except ValueError as e:
        decisions = []
        errors.append(str(e))

    gate_rejections, gate_blocks, gate_overrides = _stage_gate_summaries(state)
    tripwire_decisions = [row for row in decisions if row.get("tripwire_id")]
    open_followups = [
        row
        for row in decisions
        if row.get("outcome") in OPEN_DECISION_OUTCOMES and row.get("human_disposition") != "agree"
    ]

    tripwire_ids = {
        str(row.get("tripwire_id")) for row in tripwire_decisions if row.get("tripwire_id")
    }
    for check in tripwire_checks:
        if not isinstance(check, dict):
            continue
        for key in ("warn", "block"):
            values = check.get(key, [])
            if isinstance(values, list):
                tripwire_ids.update(str(value) for value in values)

    summary = {
        "decision_count": len(decisions),
        "escalation_count": sum(1 for row in decisions if row.get("outcome") == "escalated"),
        "open_followup_count": len(open_followups),
        "tripwire_check_count": len(tripwire_checks),
        "tripwire_decision_count": len(tripwire_decisions),
        "tripwire_warn_count": sum(
            len(check.get("warn", [])) for check in tripwire_checks if isinstance(check, dict)
        ),
        "tripwire_block_count": sum(
            len(check.get("block", [])) for check in tripwire_checks if isinstance(check, dict)
        ),
        "gate_rejection_count": len(gate_rejections),
        "gate_block_count": len(gate_blocks),
        "gate_override_count": len(gate_overrides),
    }

    details: dict = {}
    if decisions:
        details["decisions"] = [_compact_decision(row) for row in decisions[-5:]]
    if open_followups:
        details["open_followups"] = [_compact_decision(row) for row in open_followups[-5:]]
    if tripwire_checks:
        details["tripwire_checks"] = [
            _compact_tripwire_check(row) for row in tripwire_checks[-5:] if isinstance(row, dict)
        ]
    if tripwire_ids:
        details["tripwire_ids"] = sorted(tripwire_ids)
    if gate_rejections:
        details["gate_rejections"] = gate_rejections
    if gate_blocks:
        details["gate_blocks"] = gate_blocks
    if gate_overrides:
        details["gate_overrides"] = gate_overrides
    if errors:
        details["errors"] = errors

    if not any(summary.values()) and not details:
        return None
    return {**summary, **details}


def build_governance_view(
    run_id: str, state: dict, project_root: Path | None = None
) -> dict | None:
    """Merge run metadata with adoption signals for user-facing run views."""
    view = _legacy_governance_metadata(state)
    adoption = build_governance_adoption(run_id, state, project_root=project_root)
    if adoption:
        view["adoption"] = adoption
    return view or None


def _record_tripwire_check(args, result: dict) -> None:
    run_id = getattr(args, "run_id", None)
    if not run_id:
        return

    try:
        state_path, state = _load_state_for_governance(run_id, args)
    except (FileNotFoundError, ValueError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    stage = getattr(args, "stage", None)
    if stage and stage not in state.get("stages", {}):
        print(json.dumps({"error": f"Stage '{stage}' not found in run {run_id}"}), file=sys.stderr)
        sys.exit(1)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    record = {
        "ts": now,
        "stage": stage,
        "passed": len(result.get("block", [])) == 0,
        "matched": [rule["id"] for rule in result.get("matched", [])],
        "warn": result.get("warn", []),
        "block": result.get("block", []),
        "paths": result.get("paths", []),
        "artifact_type": result.get("artifact_type"),
        "decision_right": result.get("decision_right"),
    }
    record = {key: value for key, value in record.items() if value not in (None, "", [])}

    governance = state.setdefault("governance", {})
    if not isinstance(governance, dict):
        governance = {}
        state["governance"] = governance
    checks = governance.setdefault("tripwire_checks", [])
    if not isinstance(checks, list):
        checks = []
        governance["tripwire_checks"] = checks
    checks.append(record)
    state["last_update"] = now

    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)


def cmd_decision_append(args, config: dict | None = None) -> None:
    """Append a structured governance decision record."""
    outcome = args.outcome
    if outcome not in DECISION_OUTCOMES:
        print(
            json.dumps(
                {"error": f"Invalid --outcome '{outcome}'. Valid: {sorted(DECISION_OUTCOMES)}"}
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    human_disposition = getattr(args, "human_disposition", None)
    if human_disposition and human_disposition not in HUMAN_DISPOSITIONS:
        print(
            json.dumps(
                {
                    "error": "Invalid --human-disposition "
                    f"'{human_disposition}'. Valid: {sorted(HUMAN_DISPOSITIONS)}"
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    run_id = getattr(args, "run_id", None)
    if run_id:
        try:
            _load_state_for_governance(run_id, args)
        except (FileNotFoundError, ValueError) as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    entry = {
        "id": f"d-{int(time.time() * 1000)}",
        "ts": now,
        "outcome": outcome,
        "summary": args.summary,
    }

    optional_fields = {
        "initiative": getattr(args, "initiative", None),
        "phase": getattr(args, "phase", None),
        "checkpoint": getattr(args, "checkpoint", None),
        "role": getattr(args, "role", None),
        "run_id": getattr(args, "run_id", None),
        "stage": getattr(args, "stage", None),
        "artifact_type": getattr(args, "artifact_type", None),
        "artifact_ref": getattr(args, "artifact_ref", None),
        "decision_right": getattr(args, "decision_right", None),
        "tripwire_id": getattr(args, "tripwire_id", None),
        "rationale": getattr(args, "rationale", None),
        "human_disposition": human_disposition,
    }
    for field, value in optional_fields.items():
        if value is not None and value != "":
            entry[field] = value

    try:
        path = _decisions_jsonl_path(args)
    except FileNotFoundError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    _ensure_parent(path)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    print(json.dumps(entry))


def cmd_decision_list(args, config: dict | None = None) -> None:
    """List structured decision records with optional filters."""
    try:
        decisions = _read_decisions(args)
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    filters = {
        "outcome": getattr(args, "outcome", None),
        "initiative": getattr(args, "initiative", None),
        "phase": getattr(args, "phase", None),
        "role": getattr(args, "role", None),
        "run_id": getattr(args, "run_id", None),
    }
    for field, expected in filters.items():
        if expected:
            decisions = [row for row in decisions if row.get(field) == expected]

    last_n = getattr(args, "last", None)
    if last_n is not None and last_n > 0:
        decisions = decisions[-last_n:]

    print(json.dumps(decisions))


def cmd_decision_render_log(args, config: dict | None = None) -> None:
    """Render docs/decisions/log.md from structured decision records."""
    try:
        decisions = _read_decisions(args)
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    target = (
        Path(args.output).resolve()
        if getattr(args, "output", None)
        else _decision_log_markdown_path(args).resolve()
    )
    _ensure_parent(target)

    lines: list[str] = []
    lines.append("# Decision Log")
    lines.append("")
    lines.append("Generated from `.agenteam/governance/decisions.jsonl`.")
    lines.append("")
    if not decisions:
        lines.append("_No decisions recorded yet._")
    else:
        for row in decisions:
            summary = row.get("summary", "").strip()
            ts = row.get("ts", "")
            rid = row.get("id", "")
            outcome = row.get("outcome", "")
            lines.append(f"## {rid} - {outcome} ({ts})")
            lines.append("")
            lines.append(f"- Summary: {summary}")

            optional_order = [
                ("initiative", "Initiative"),
                ("phase", "Phase"),
                ("checkpoint", "Checkpoint"),
                ("role", "Role"),
                ("run_id", "Run"),
                ("stage", "Stage"),
                ("artifact_type", "Artifact type"),
                ("artifact_ref", "Artifact ref"),
                ("decision_right", "Decision right"),
                ("tripwire_id", "Tripwire"),
                ("human_disposition", "Human disposition"),
            ]
            for key, label in optional_order:
                value = row.get(key)
                if value:
                    lines.append(f"- {label}: {value}")
            rationale = row.get("rationale")
            if rationale:
                lines.append(f"- Rationale: {rationale}")
            lines.append("")

    with open(target, "w") as f:
        f.write("\n".join(lines).rstrip() + "\n")

    print(
        json.dumps(
            {
                "ok": True,
                "output": str(target),
                "count": len(decisions),
            }
        )
    )


def cmd_tripwire_check(args, config: dict | None = None) -> None:
    """Evaluate a minimal tripwire catalog against provided context."""
    try:
        tripwires = _load_tripwires(args)
    except (ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)

    paths = getattr(args, "path", None) or []
    artifact_type = getattr(args, "artifact_type", None)
    decision_right = getattr(args, "decision_right", None)

    matched = [
        tripwire
        for tripwire in tripwires
        if _tripwire_matches(tripwire, paths, artifact_type, decision_right)
    ]

    result = {
        "ok": True,
        "matched": matched,
        "warn": [rule["id"] for rule in matched if rule.get("severity") == "warn"],
        "block": [rule["id"] for rule in matched if rule.get("severity") == "block"],
        "passed": not any(rule.get("severity") == "block" for rule in matched),
        "paths": paths,
        "artifact_type": artifact_type,
        "decision_right": decision_right,
    }
    if getattr(args, "run_id", None):
        _record_tripwire_check(args, result)
        result["recorded"] = True
    print(json.dumps(result))
