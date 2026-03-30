#!/usr/bin/env python3
"""AgenTeam runtime -- compatibility wrapper.

Preserves the CLI contract: python3 runtime/agenteam_rt.py <command>
Dependency guards ensure missing PyYAML/toml produce JSON errors, not tracebacks.
"""
import json
import sys

try:
    import yaml  # noqa: F401
except ImportError:
    print(json.dumps({"error": "PyYAML not installed. Run: pip install pyyaml"}), file=sys.stderr)
    sys.exit(1)

try:
    import toml  # noqa: F401
except ImportError:
    print(json.dumps({"error": "toml not installed. Run: pip install toml"}), file=sys.stderr)
    sys.exit(1)

from agenteam.cli import main

if __name__ == "__main__":
    main()
