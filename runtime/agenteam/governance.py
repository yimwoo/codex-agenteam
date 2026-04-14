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


def _read_decisions(args=None) -> list[dict]:
    path = _decisions_jsonl_path(args)
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


def _load_tripwires(args=None) -> list[dict]:
    path = _tripwires_config_path(args)
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
    if run_id and not _RUN_ID_RE.match(run_id):
        print(
            json.dumps(
                {
                    "error": f"Invalid --run-id '{run_id}'. "
                    "Must contain only alphanumeric characters, hyphens, and underscores."
                }
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    if run_id:
        try:
            state_path = _project_root(args) / ".agenteam" / "state" / f"{run_id}.json"
        except FileNotFoundError as e:
            print(json.dumps({"error": str(e)}), file=sys.stderr)
            sys.exit(1)
        if not state_path.exists():
            print(
                json.dumps({"error": f"Run {run_id} not found"}),
                file=sys.stderr,
            )
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
        "paths": paths,
        "artifact_type": artifact_type,
        "decision_right": decision_right,
    }
    print(json.dumps(result))
