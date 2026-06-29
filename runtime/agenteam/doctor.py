"""Local Codex compatibility diagnostics for AgenTeam."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from typing import Any

import yaml

from .config import find_config, load_config_merged_raw
from .constants import DEPRECATED_CODEX_MODELS
from .roles import resolve_roles

SCHEMA_VERSION = "1"
RELEVANT_FEATURES = {
    "fast_mode",
    "goals",
    "hooks",
    "memories",
    "multi_agent",
    "plugin_sharing",
    "plugins",
    "unified_exec",
}
_VERSION_RE = re.compile(r"\b(\d+\.\d+(?:\.\d+)?(?:[-+][A-Za-z0-9.-]+)?)\b")


def _diagnostic(severity: str, code: str, message: str, path: str | None = None) -> dict:
    finding = {"severity": severity, "code": code, "message": message}
    if path is not None:
        finding["path"] = path
    return finding


def _parse_version(output: str) -> str | None:
    """Extract a semantic-looking version from Codex CLI output."""
    match = _VERSION_RE.search(output)
    return match.group(1) if match else None


def _parse_features(output: str) -> dict[str, dict[str, Any]]:
    """Parse the stable tabular output of `codex features list`."""
    features: dict[str, dict[str, Any]] = {}
    for raw_line in output.splitlines():
        parts = raw_line.split()
        if len(parts) < 3 or parts[0] not in RELEVANT_FEATURES:
            continue
        enabled_text = parts[-1].lower()
        if enabled_text not in {"true", "false"}:
            continue
        features[parts[0]] = {
            "stage": " ".join(parts[1:-1]),
            "enabled": enabled_text == "true",
        }
    return features


def _run_codex(
    binary: str,
    command: list[str],
    timeout_seconds: float,
) -> subprocess.CompletedProcess[str]:
    """Run a bounded, non-shell Codex diagnostic command."""
    return subprocess.run(  # noqa: S603
        [binary, *command],
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _inspect_codex(
    requested_binary: str,
    timeout_seconds: float,
    diagnostics: list[dict],
) -> tuple[dict, dict[str, dict[str, Any]]]:
    resolved_binary = shutil.which(requested_binary)
    codex = {
        "available": resolved_binary is not None,
        "requested_binary": requested_binary,
        "resolved_binary": resolved_binary,
        "version": None,
    }
    if resolved_binary is None:
        diagnostics.append(
            _diagnostic(
                "error",
                "D001",
                f"Codex binary not found: '{requested_binary}'.",
                "codex.binary",
            )
        )
        return codex, {}

    try:
        version_result = _run_codex(resolved_binary, ["--version"], timeout_seconds)
    except subprocess.TimeoutExpired:
        diagnostics.append(
            _diagnostic(
                "error",
                "D002",
                f"Codex version check exceeded {timeout_seconds:g} seconds.",
                "codex.version",
            )
        )
        return codex, {}
    except OSError as exc:
        diagnostics.append(
            _diagnostic(
                "error",
                "D002",
                f"Codex version check failed: {exc}.",
                "codex.version",
            )
        )
        return codex, {}

    version_output = "\n".join(
        part.strip() for part in (version_result.stdout, version_result.stderr) if part.strip()
    )
    codex["version"] = _parse_version(version_output)
    if version_result.returncode != 0 or codex["version"] is None:
        diagnostics.append(
            _diagnostic(
                "error",
                "D002",
                "Codex version check did not return a recognized version.",
                "codex.version",
            )
        )
        return codex, {}

    try:
        feature_result = _run_codex(resolved_binary, ["features", "list"], timeout_seconds)
    except (OSError, subprocess.TimeoutExpired) as exc:
        diagnostics.append(
            _diagnostic(
                "warning",
                "D003",
                f"Codex feature discovery was unavailable: {exc}.",
                "codex.features",
            )
        )
        return codex, {}

    features = _parse_features(feature_result.stdout) if feature_result.returncode == 0 else {}
    if feature_result.returncode != 0:
        diagnostics.append(
            _diagnostic(
                "warning",
                "D003",
                "Codex feature discovery returned a non-zero exit code.",
                "codex.features",
            )
        )
    elif not features:
        diagnostics.append(
            _diagnostic(
                "warning",
                "D003",
                "Codex feature discovery returned no recognized AgenTeam capabilities.",
                "codex.features",
            )
        )
    return codex, features


def _inspect_config(config_arg: str | None, diagnostics: list[dict]) -> dict:
    config_info: dict[str, Any] = {"found": False, "path": None, "model_pins": []}
    try:
        config_path = find_config(config_arg)
    except FileNotFoundError as exc:
        if config_arg:
            diagnostics.append(_diagnostic("error", "D004", str(exc), "config"))
        return config_info

    config_info["found"] = True
    config_info["path"] = str(config_path)
    try:
        config = load_config_merged_raw(config_path)
        role_overrides = config.get("roles", {})
        if not isinstance(role_overrides, dict):
            raise ValueError("Config field 'roles' must be a mapping")
        roles = resolve_roles(config)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        diagnostics.append(
            _diagnostic("error", "D004", f"Failed to inspect AgenTeam config: {exc}.", "config")
        )
        return config_info

    model_pins = []
    for role_name in sorted(roles):
        model = roles[role_name].get("model")
        if not isinstance(model, str) or not model:
            continue
        deprecated = model in DEPRECATED_CODEX_MODELS
        model_pins.append({"role": role_name, "model": model, "deprecated": deprecated})
        if deprecated:
            diagnostics.append(
                _diagnostic(
                    "warning",
                    "D005",
                    f"Role '{role_name}' pins deprecated Codex model '{model}'. Remove the pin "
                    "to use Codex's recommended default or choose a model available in your "
                    "environment.",
                    f"roles.{role_name}.model",
                )
            )
    config_info["model_pins"] = model_pins
    return config_info


def build_doctor_report(
    *,
    codex_bin: str,
    timeout_seconds: float,
    config_arg: str | None,
) -> dict:
    """Build a side-effect-free local Codex compatibility report."""
    diagnostics: list[dict] = []
    codex, features = _inspect_codex(codex_bin, timeout_seconds, diagnostics)
    config = _inspect_config(config_arg, diagnostics)
    has_error = any(item["severity"] == "error" for item in diagnostics)
    return {
        "schema_version": SCHEMA_VERSION,
        "ready": codex["available"] and codex["version"] is not None and not has_error,
        "codex": codex,
        "features": features,
        "config": config,
        "diagnostics": diagnostics,
    }


def cmd_doctor(args) -> None:
    """Print local Codex and AgenTeam compatibility diagnostics as JSON."""
    report = build_doctor_report(
        codex_bin=args.codex_bin,
        timeout_seconds=args.timeout_seconds,
        config_arg=getattr(args, "config", None) or None,
    )
    print(json.dumps(report))
    if args.strict and any(
        item["severity"] in {"warning", "error"} for item in report["diagnostics"]
    ):
        sys.exit(1)
