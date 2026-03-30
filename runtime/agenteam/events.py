"""Event log: append-only JSONL event stream for run history."""

import json
import sys
import time
from pathlib import Path

# Event types and their required data fields.
EVENT_TYPES: dict[str, list[str]] = {
    "run_started": ["task", "pipeline_mode"],
    "stage_dispatched": ["roles", "isolation"],
    "stage_verified": ["result", "command", "attempt"],
    "stage_gated": ["gate_type", "result"],
    "stage_completed": ["result"],
    "stage_resumed": ["verify_result", "action"],
    "run_finished": ["status"],
}

# Events that require a non-null stage field.
_STAGE_EVENTS = {
    "stage_dispatched",
    "stage_verified",
    "stage_gated",
    "stage_completed",
    "stage_resumed",
}


def append_event(
    run_id: str,
    event_type: str,
    stage: str | None,
    data: dict,
) -> dict:
    """Validate and append one event to the JSONL file.

    Returns the event dict that was written.
    Raises SystemExit on validation failure.
    """
    if event_type not in EVENT_TYPES:
        print(
            json.dumps({
                "error": f"Unknown event type '{event_type}'."
                f" Valid: {sorted(EVENT_TYPES)}",
            }),
            file=sys.stderr,
        )
        sys.exit(1)

    required = EVENT_TYPES[event_type]
    missing = [f for f in required if f not in data]
    if missing:
        print(
            json.dumps({
                "error": f"Missing required data fields for '{event_type}': {missing}",
            }),
            file=sys.stderr,
        )
        sys.exit(1)

    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "type": event_type,
        "run_id": run_id,
        "stage": stage,
        "data": data,
    }

    events_dir = Path.cwd() / ".agenteam" / "events"
    events_dir.mkdir(parents=True, exist_ok=True)

    events_path = events_dir / f"{run_id}.jsonl"
    with open(events_path, "a") as f:
        f.write(json.dumps(event) + "\n")

    return event


def list_events(
    run_id: str,
    type_filter: str | None = None,
    stage_filter: str | None = None,
    last_n: int | None = None,
) -> list[dict]:
    """Read and filter events from the JSONL file.

    Returns empty list if the file does not exist.
    """
    events_path = Path.cwd() / ".agenteam" / "events" / f"{run_id}.jsonl"
    if not events_path.exists():
        return []

    events: list[dict] = []
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))

    if type_filter:
        events = [e for e in events if e.get("type") == type_filter]

    if stage_filter:
        events = [e for e in events if e.get("stage") == stage_filter]

    if last_n is not None and last_n > 0:
        events = events[-last_n:]

    return events


def cmd_event_append(args, config: dict | None = None) -> None:
    """CLI handler for: agenteam-rt event append."""
    run_id = args.run_id
    event_type = args.type
    stage = args.stage if args.stage else None
    try:
        data = json.loads(args.data) if args.data else {}
    except json.JSONDecodeError as e:
        print(json.dumps({"error": f"Invalid JSON in --data: {e}"}), file=sys.stderr)
        sys.exit(1)

    event = append_event(run_id, event_type, stage, data)
    print(json.dumps(event))


def cmd_event_list(args, config: dict | None = None) -> None:
    """CLI handler for: agenteam-rt event list."""
    run_id = args.run_id
    type_filter = args.type if hasattr(args, "type") and args.type else None
    stage_filter = args.stage if hasattr(args, "stage") and args.stage else None
    last_n = args.last if hasattr(args, "last") and args.last else None

    events = list_events(run_id, type_filter, stage_filter, last_n)
    print(json.dumps(events))
