# v3.13 Structured Role Handoffs And Provenance

Status: accepted for implementation

## Context

AgenTeam role templates describe handoffs in prose, but the runner currently
captures only Codex JSONL events, stdout, stderr, prompt data, and execution
metadata. Downstream roles and evidence consumers cannot distinguish a valid
role result from an unstructured final message without reopening transcripts.

Codex CLI 0.137.0 and the current Codex manual document:

- `codex exec --output-schema <schema.json>` for schema-constrained final
  responses.
- `-o` / `--output-last-message` for writing that final response to a file.
- stable lifecycle hooks with explicit trust review for non-managed commands.

The manual documents hook discovery, trust, events, and configuration, but not
the command-handler stdin/stdout payload contract. AgenTeam must not guess a
security-sensitive hook protocol.

## Decision

Implement the structured-handoff and provenance half of Phase C first. Keep
native hook commands deferred until their payload contract is documented or
verified against a supported Codex schema.

Structured handoffs are opt-in through:

```yaml
structured_handoffs: true
```

When enabled, every runner-managed role execution:

1. Passes AgenTeam's versioned JSON Schema to `codex exec --output-schema`.
2. Writes the final response to the role's `handoff.json` artifact with `-o`.
3. Validates the persisted handoff before accepting the role as successful.
4. Records compact provenance in run state and events.
5. Makes valid prior handoffs visible to later role prompts.

Existing prompt, stdout, stderr, JSONL, and execution artifacts remain
available. Structured handoffs do not replace final verification, gates, or
scope auditing.

## Handoff Schema

The bundled `role-handoff-v1.json` schema requires:

```json
{
  "status": "completed",
  "summary": "Implemented the requested change.",
  "artifacts": ["runtime/agenteam/example.py"],
  "verification": [
    {"command": "pytest -q", "result": "passed", "details": "358 passed"}
  ],
  "findings": [],
  "recommended_next_stage": "test"
}
```

Rules:

- `status`: `completed`, `blocked`, or `failed`.
- `summary`: non-empty string.
- `artifacts`: repository-relative path strings. The runtime rejects
  duplicates because Codex Structured Outputs does not support JSON Schema's
  `uniqueItems` keyword.
- `verification`: command/result objects; result is `passed`, `failed`, or
  `skipped`.
- `findings`: optional structured BLOCK/WARN/NOTE-style findings represented
  as objects in a required array.
- `recommended_next_stage`: non-empty string or `null`.
- Unknown top-level and nested fields are rejected.

The runtime repeats a small deterministic validation after Codex returns. This
protects fake executors, older Codex versions, interrupted writes, and future
executor backends that may not enforce the CLI schema themselves.

## Artifacts And State

Each structured role execution adds:

```text
.agenteam/runs/<run-id>/<stage>/<role>/handoff.json
```

The stage state records one compact entry per role:

```json
{
  "role": "dev",
  "path": ".agenteam/runs/<run-id>/implement/dev/handoff.json",
  "schema_version": "1",
  "sha256": "...",
  "status": "completed",
  "summary": "Implemented the requested change.",
  "artifact_count": 2,
  "verification_count": 1,
  "finding_count": 0,
  "recommended_next_stage": "test"
}
```

Raw handoff content remains in the artifact file. State, trace, and evidence
carry only the compact summary and provenance needed by downstream consumers.

## Events

Add two runtime event types:

- `role_handoff_recorded`: emitted after a valid handoff is persisted and
  hashed.
- `role_handoff_invalid`: emitted when the output file is missing, malformed,
  or violates the runtime contract.

An invalid handoff makes that role execution fail even when Codex exits zero.
The runner uses an AgenTeam-owned negative exit code and preserves the
validation reason in `exec.json`, stderr, and event data.

## Prompt Integration

Later roles receive a `Prior Structured Handoffs` prompt section assembled
from valid state entries in earlier stages. The section includes role, stage,
status, summary, path, and recommended next stage. It never embeds raw stdout,
stderr, prompts, or unvalidated handoff files.

The existing mtime-based artifact discovery remains as a compatibility
fallback for non-runner artifacts and runs without structured handoffs.

## Evidence Integration

Trace stage entries expose recorded handoff summaries. Evidence includes those
summaries and adds:

- `handoff_count`
- `invalid_handoff_count`

This makes structured completion observable to benchmark and release-review
consumers without changing the evidence schema version; the fields are
additive in schema version 1.

## Configuration And Compatibility

- Default is `false`; existing projects and fake Codex scripts keep their
  current behavior.
- `structured_handoffs` must be boolean when present.
- AgenTeam owns `--output-schema` and `--output-last-message` while structured
  handoffs are enabled. Conflicting passthrough arguments fail before launch.
- The schema path is resolved from the installed runtime package, not the
  project working directory.
- The feature works in branch, worktree, and no-isolation modes.

## Hook Boundary

Do not bundle or scaffold executable hooks in this slice. Before adding them:

1. Verify the official command-handler input/output contract.
2. Define which events are advisory versus blocking.
3. Keep trust review visible through Codex `/hooks`.
4. Ensure hook failure cannot bypass authoritative runtime verification.
5. Add compatibility diagnostics for hooks disabled by user or admin policy.

Candidate later hooks remain `SubagentStart`, `SubagentStop`, `PreToolUse`,
`PermissionRequest`, `PostToolUse`, and `Stop`.

## Verification

- Config validation accepts booleans and rejects other values.
- Runner command construction uses the bundled schema and role-local output
  path only when enabled.
- Valid handoffs are hashed, recorded, exposed in trace/evidence, and included
  in later prompts.
- Missing, malformed, and contract-invalid handoffs fail the role.
- Passthrough output-schema conflicts fail safely.
- Disabled mode remains byte-for-byte compatible at the command boundary.
- Full runtime, formatting, smoke, isolation, and plugin validation suites pass.

## Sources

- [Codex non-interactive structured outputs](https://developers.openai.com/codex/noninteractive#structured-output)
- [Codex hooks](https://developers.openai.com/codex/hooks)
