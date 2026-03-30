"""Schema validation framework for AgenTeam config files."""

import difflib
from dataclasses import dataclass, field
from enum import Enum

from .constants import (
    KNOWN_TOP_LEVEL_KEYS,
    VALID_FINAL_VERIFY_POLICIES,
    VALID_ISOLATION,
    VALID_PIPELINES,
    VALID_VERSIONS,
    VALID_WRITE_MODES,
)


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Diagnostic:
    """A single validation finding."""

    severity: Severity
    path: str
    message: str
    code: str

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "path": self.path,
            "message": self.message,
            "code": self.code,
        }


@dataclass
class ValidationResult:
    """Aggregated result of all validation passes."""

    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(d.severity == Severity.ERROR for d in self.diagnostics)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.WARNING]

    @property
    def infos(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == Severity.INFO]

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }


def _suggest(name: str, candidates: set[str] | list[str]) -> str:
    """Return a 'Did you mean ...?' suffix, or empty string."""
    matches = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    if matches:
        return f" Did you mean '{matches[0]}'?"
    return ""


def validate_schema(
    config: dict,
    resolved_roles: dict | None = None,
) -> ValidationResult:
    """Run all validation passes and return aggregated result."""
    result = ValidationResult()
    _pass_required_fields(config, result)
    _pass_top_level_enums(config, result)
    _pass_legacy_keys(config, result)
    _pass_pipeline_stages(config, result)
    _pass_final_verify(config, result)
    if resolved_roles is not None:
        _pass_cross_references(config, resolved_roles, result)
    _pass_profiles(config, result)
    _pass_unknown_keys(config, result)
    _pass_version_info(config, result)
    return result


# ---------------------------------------------------------------------------
# Pass 1: Required fields
# ---------------------------------------------------------------------------


def _pass_required_fields(config: dict, result: ValidationResult) -> None:
    if "version" not in config:
        result.diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                "version",
                "Missing required field: version",
                "E001",
            )
        )
        return

    version = str(config["version"])
    if version not in VALID_VERSIONS:
        result.diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                "version",
                f"Invalid version: '{version}'. "
                f"Must be one of: {', '.join(sorted(VALID_VERSIONS))}",
                "E001",
            )
        )


# ---------------------------------------------------------------------------
# Pass 2: Top-level enums
# ---------------------------------------------------------------------------


def _pass_top_level_enums(config: dict, result: ValidationResult) -> None:
    isolation = config.get("isolation")
    if isolation and isolation not in VALID_ISOLATION:
        result.diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                "isolation",
                f"Invalid isolation: '{isolation}'. "
                f"Must be one of: {', '.join(sorted(VALID_ISOLATION))}",
                "E002",
            )
        )

    pipeline_val = config.get("pipeline")
    if isinstance(pipeline_val, str) and pipeline_val != "hotl":
        result.diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                "pipeline",
                f"Invalid pipeline: '{pipeline_val}'. Only 'hotl' is valid as a top-level string. "
                "Omit for auto-detect, or use pipeline.stages for stage definitions.",
                "E003",
            )
        )

    fvp = config.get("final_verify_policy")
    if fvp is not None and fvp not in VALID_FINAL_VERIFY_POLICIES:
        result.diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                "final_verify_policy",
                f"Invalid final_verify_policy: '{fvp}'. "
                f"Must be one of: {', '.join(sorted(VALID_FINAL_VERIFY_POLICIES))}",
                "E013",
            )
        )

    fvmr = config.get("final_verify_max_retries")
    if fvmr is not None:
        if not isinstance(fvmr, int) or isinstance(fvmr, bool) or fvmr < 0:
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    "final_verify_max_retries",
                    f"final_verify_max_retries must be a non-negative integer, got '{fvmr}'",
                    "E014",
                )
            )


# ---------------------------------------------------------------------------
# Pass 3: Legacy keys
# ---------------------------------------------------------------------------


def _pass_legacy_keys(config: dict, result: ValidationResult) -> None:
    team = config.get("team")
    if team is None:
        return

    if not isinstance(team, dict):
        result.diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                "team",
                "'team' must be a mapping",
                "E017",
            )
        )
        return

    legacy_pipeline = team.get("pipeline")
    if legacy_pipeline is not None:
        if legacy_pipeline not in VALID_PIPELINES:
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    "team.pipeline",
                    f"Invalid team.pipeline: '{legacy_pipeline}'. "
                    f"Must be one of: {', '.join(sorted(VALID_PIPELINES))}",
                    "E018",
                )
            )
        else:
            result.diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    "team.pipeline",
                    f"Legacy config format detected at team.pipeline: '{legacy_pipeline}'. "
                    "Run 'agenteam-rt migrate' to convert to the canonical schema. "
                    "Legacy support will be removed in a future major release.",
                    "W001",
                )
            )

    pw = team.get("parallel_writes")
    if isinstance(pw, dict):
        mode = pw.get("mode")
        if mode is not None:
            if mode not in VALID_WRITE_MODES:
                result.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        "team.parallel_writes.mode",
                        f"Invalid team.parallel_writes.mode: '{mode}'. "
                        f"Must be one of: {', '.join(sorted(VALID_WRITE_MODES))}",
                        "E019",
                    )
                )
            else:
                result.diagnostics.append(
                    Diagnostic(
                        Severity.WARNING,
                        "team.parallel_writes.mode",
                        f"Legacy config format detected at team.parallel_writes.mode: '{mode}'. "
                        f"Run 'agenteam-rt migrate' to convert to the canonical schema. "
                        "Legacy support will be removed in a future major release.",
                        "W002",
                    )
                )


# ---------------------------------------------------------------------------
# Pass 4: Pipeline stages
# ---------------------------------------------------------------------------


def _pass_pipeline_stages(config: dict, result: ValidationResult) -> None:
    from .constants import VALID_GATE_TYPES

    pipeline_val = config.get("pipeline")
    if not isinstance(pipeline_val, dict):
        return

    stages = pipeline_val.get("stages")
    if stages is None:
        return

    if not isinstance(stages, list):
        result.diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                "pipeline.stages",
                "pipeline.stages must be a list",
                "E004",
            )
        )
        return

    seen_names: dict[str, int] = {}
    stage_names: set[str] = set()

    for i, stage in enumerate(stages):
        prefix = f"pipeline.stages[{i}]"

        if not isinstance(stage, dict):
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    prefix,
                    f"{prefix}: stage must be a mapping",
                    "E005",
                )
            )
            continue

        name = stage.get("name")
        if not name or not isinstance(name, str):
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f"{prefix}.name",
                    f"{prefix}.name: stage must have a 'name' string field",
                    "E005",
                )
            )
            continue

        stage_names.add(name)

        if name in seen_names:
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f"{prefix}.name",
                    f"Duplicate stage name '{name}' at positions {seen_names[name]} and {i}",
                    "E011",
                )
            )
        else:
            seen_names[name] = i

        roles = stage.get("roles")
        if roles is not None and (not isinstance(roles, list)):
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f"{prefix}.roles",
                    f"{prefix}.roles: must be a list",
                    "E006",
                )
            )

        gate = stage.get("gate")
        if gate is not None and gate not in VALID_GATE_TYPES:
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f"{prefix}.gate",
                    f"{prefix}.gate: invalid gate '{gate}'. "
                    f"Must be one of: {', '.join(sorted(VALID_GATE_TYPES))}",
                    "E015",
                )
            )

        max_retries = stage.get("max_retries")
        if max_retries is not None:
            if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
                result.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f"{prefix}.max_retries",
                        f"{prefix}.max_retries: must be a non-negative "
                        f"integer, got '{max_retries}'",
                        "E016",
                    )
                )

    # Second pass for rework_to (needs all stage names collected)
    for i, stage in enumerate(stages):
        if not isinstance(stage, dict):
            continue
        rework_to = stage.get("rework_to")
        if rework_to is not None and rework_to not in stage_names:
            prefix = f"pipeline.stages[{i}].rework_to"
            suggestion = _suggest(rework_to, stage_names)
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    prefix,
                    f"{prefix}: references non-existent stage '{rework_to}'.{suggestion}",
                    "E008",
                )
            )


# ---------------------------------------------------------------------------
# Pass 5: Final verify
# ---------------------------------------------------------------------------


def _pass_final_verify(config: dict, result: ValidationResult) -> None:
    fv = config.get("final_verify")
    if fv is None:
        return

    if isinstance(fv, str):
        result.diagnostics.append(
            Diagnostic(
                Severity.WARNING,
                "final_verify",
                'final_verify is a string. Consider using a list: final_verify: ["..."]',
                "W004",
            )
        )
    elif isinstance(fv, list):
        for i, item in enumerate(fv):
            if not isinstance(item, str):
                result.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f"final_verify[{i}]",
                        f"final_verify[{i}]: must be a string, got {type(item).__name__}",
                        "E013",
                    )
                )
    else:
        result.diagnostics.append(
            Diagnostic(
                Severity.ERROR,
                "final_verify",
                "final_verify must be a list of command strings",
                "E013",
            )
        )


# ---------------------------------------------------------------------------
# Pass 6: Cross-references
# ---------------------------------------------------------------------------


def _pass_cross_references(
    config: dict,
    resolved_roles: dict,
    result: ValidationResult,
) -> None:
    from .constants import VALID_REASONING_EFFORT

    pipeline_val = config.get("pipeline")
    if isinstance(pipeline_val, dict):
        stages = pipeline_val.get("stages", [])
        if isinstance(stages, list):
            role_names = set(resolved_roles.keys())
            for i, stage in enumerate(stages):
                if not isinstance(stage, dict):
                    continue
                roles = stage.get("roles", [])
                if not isinstance(roles, list):
                    continue
                for role_name in roles:
                    if isinstance(role_name, str) and role_name not in role_names:
                        prefix = f"pipeline.stages[{i}].roles"
                        suggestion = _suggest(role_name, role_names)
                        result.diagnostics.append(
                            Diagnostic(
                                Severity.ERROR,
                                prefix,
                                f"{prefix}: unknown role '{role_name}'.{suggestion}",
                                "E007",
                            )
                        )

    # Validate reasoning_effort in role overrides
    role_overrides = config.get("roles", {})
    if isinstance(role_overrides, dict):
        for role_name, role_cfg in role_overrides.items():
            if isinstance(role_cfg, dict):
                re_val = role_cfg.get("reasoning_effort")
                if re_val is not None and re_val not in VALID_REASONING_EFFORT:
                    result.diagnostics.append(
                        Diagnostic(
                            Severity.ERROR,
                            f"roles.{role_name}.reasoning_effort",
                            f"roles.{role_name}.reasoning_effort: invalid value '{re_val}'. "
                            f"Must be one of: {', '.join(sorted(VALID_REASONING_EFFORT))}",
                            "E002",
                        )
                    )


# ---------------------------------------------------------------------------
# Pass 7: Profiles
# ---------------------------------------------------------------------------


def _pass_profiles(config: dict, result: ValidationResult) -> None:
    pipeline_val = config.get("pipeline")
    if not isinstance(pipeline_val, dict):
        return

    profiles = pipeline_val.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return

    # Collect valid stage names
    stages_list = pipeline_val.get("stages", [])
    valid_stage_names: set[str] = set()
    stage_rework_map: dict[str, str | None] = {}
    if isinstance(stages_list, list):
        for s in stages_list:
            if isinstance(s, dict) and "name" in s:
                valid_stage_names.add(s["name"])
                stage_rework_map[s["name"]] = s.get("rework_to")

    for profile_name, profile_def in profiles.items():
        prefix = f"pipeline.profiles.{profile_name}"

        if not isinstance(profile_def, dict):
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    prefix,
                    f"{prefix}: profile must be a mapping",
                    "E010",
                )
            )
            continue

        stages = profile_def.get("stages")
        if not stages or not isinstance(stages, list):
            result.diagnostics.append(
                Diagnostic(
                    Severity.ERROR,
                    f"{prefix}.stages",
                    f"{prefix}.stages: must be a non-empty list",
                    "E010",
                )
            )
            continue

        profile_stage_set: set[str] = set()
        for j, sname in enumerate(stages):
            if not isinstance(sname, str):
                result.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f"{prefix}.stages[{j}]",
                        f"{prefix}.stages[{j}]: stage names must be strings, "
                        f"got {type(sname).__name__}",
                        "E009",
                    )
                )
            elif sname not in valid_stage_names:
                suggestion = _suggest(sname, valid_stage_names)
                result.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f"{prefix}.stages[{j}]",
                        f"{prefix}.stages[{j}]: unknown stage '{sname}'.{suggestion}",
                        "E009",
                    )
                )
            elif sname in profile_stage_set:
                result.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f"{prefix}.stages[{j}]",
                        f"{prefix}: duplicate stage '{sname}'",
                        "E012",
                    )
                )
            else:
                profile_stage_set.add(sname)

        # Cross-stage rework validation within profile
        for sname in profile_stage_set:
            rework_target = stage_rework_map.get(sname)
            if rework_target and rework_target not in profile_stage_set:
                result.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f"{prefix}",
                        f"{prefix}: stage '{sname}' has rework_to '{rework_target}' "
                        f"which is not in this profile",
                        "E020",
                    )
                )

        # Hints validation
        hints = profile_def.get("hints")
        if hints is not None:
            if not isinstance(hints, list) or not all(isinstance(h, str) for h in hints):
                result.diagnostics.append(
                    Diagnostic(
                        Severity.ERROR,
                        f"{prefix}.hints",
                        f"{prefix}.hints: must be a list of strings",
                        "E010",
                    )
                )


# ---------------------------------------------------------------------------
# Unknown keys
# ---------------------------------------------------------------------------


def _pass_unknown_keys(config: dict, result: ValidationResult) -> None:
    for key in config:
        if key not in KNOWN_TOP_LEVEL_KEYS:
            suggestion = _suggest(key, KNOWN_TOP_LEVEL_KEYS)
            result.diagnostics.append(
                Diagnostic(
                    Severity.WARNING,
                    key,
                    f"Unknown top-level key '{key}'.{suggestion}",
                    "W005",
                )
            )


# ---------------------------------------------------------------------------
# Version info
# ---------------------------------------------------------------------------


def _pass_version_info(config: dict, result: ValidationResult) -> None:
    """Emit I003 if config uses new shape but version is still "1"."""
    version = str(config.get("version", ""))
    if version != "1":
        return

    # Check if there are any legacy keys (team.pipeline or team.parallel_writes)
    team = config.get("team", {})
    has_legacy = False
    if isinstance(team, dict):
        has_legacy = "pipeline" in team or "parallel_writes" in team

    # Only emit info if NO legacy keys — config is already new shape
    if not has_legacy:
        result.diagnostics.append(
            Diagnostic(
                Severity.INFO,
                "version",
                'Config uses the current schema but version is "1". '
                "Consider setting version: \"2\" or running 'agenteam-rt migrate'.",
                "I003",
            )
        )
