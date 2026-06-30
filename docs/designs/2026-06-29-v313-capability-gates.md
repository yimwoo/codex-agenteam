# v3.13 Codex Capability Gates

Status: accepted for implementation

## Context

Structured handoffs now depend on two stable `codex exec` flags:

- `--output-schema`
- `-o` / `--output-last-message`

Codex also reports lifecycle hooks through `codex features list`. Hooks are
stable and enabled by default in current Codex builds, but users or managed
requirements can disable them. Non-managed command hooks additionally require
explicit trust review.

AgenTeam's doctor command currently reports the Codex version and selected
feature stages, but it does not distinguish between a binary that can run the
legacy executor and one that can satisfy the structured-handoff contract.

The current Codex manual documents hook discovery, configuration, matching,
and trust. It still does not define a stable command-handler stdin/stdout
decision protocol. AgenTeam must not bundle policy-enforcing hook commands
until that protocol is verifiable.

## Decision

Extend `agenteam-rt doctor` with an additive `capabilities` object:

```json
{
  "capabilities": {
    "structured_output": {
      "available": true,
      "output_schema": true,
      "output_last_message": true,
      "source": "codex exec --help"
    },
    "hooks": {
      "reported": true,
      "stage": "stable",
      "enabled": true,
      "source": "codex features list"
    }
  }
}
```

Capability discovery remains local, bounded, non-shell, and side-effect free.

## Diagnostics

- `D006` warning: `codex exec --help` could not be inspected.
- `D007` error: `structured_handoffs: true` requires
  `--output-schema`, but the installed Codex does not report it.
- `D008` error: `structured_handoffs: true` requires
  `--output-last-message`, but the installed Codex does not report it.
- `D009` info: Codex reports hooks as disabled. This does not block current
  AgenTeam execution because no lifecycle hooks are bundled.

Errors make `ready` false. Warnings retain the existing `ready` behavior but
fail `doctor --strict`. Informational diagnostics do neither.

## Compatibility

- The doctor schema version stays at `1`; all new fields are additive.
- Projects without config still receive capability data.
- Projects without structured handoffs remain runnable on older Codex builds.
- The runtime keeps its existing authoritative verification, gate, and scope
  checks regardless of hook availability.

## Hook Boundary

This slice does not create `hooks/hooks.json`, add hook commands, bypass hook
trust, or inspect user hook definitions. A future hook slice still requires:

1. A supported handler input/output contract.
2. Event-specific advisory versus blocking semantics.
3. Trust-visible installation and update behavior.
4. Tests proving hook failure cannot bypass runtime verification.

## Verification

- Doctor detects both structured-output flags from fake and real Codex help.
- Structured-handoff config fails readiness when either required flag is
  missing.
- Disabled hooks produce a non-blocking informational diagnostic.
- Feature discovery and exec-help failures remain structured and traceback
  free.
- Existing doctor consumers and non-structured projects retain their behavior.

## Sources

- [Codex non-interactive structured output](https://developers.openai.com/codex/noninteractive#structured-output)
- [Codex hooks](https://developers.openai.com/codex/hooks)
