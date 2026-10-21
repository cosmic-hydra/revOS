# scripts/ — revOS harness wrappers and validators

This directory is owned by the `curator` agent and provides the only
machine-readable surface that subsystem agents should call when collecting
evidence. The shape every wrapper emits is captured in
`scripts/bin/output-schema.json`; the schema for *evidence records* is at
the top of the repo in `evidence/schema.json`.

## Wrappers (`scripts/bin/*`)

All wrappers accept a Mach-O / dylib / framework path as the last positional
argument and emit one JSON document on stdout. Every wrapper has `--help`.

| Wrapper | Tool | When to use it |
|---|---|---|
| `otool-exports` | `otool` | Pull linked libraries and `-Iv` exports for a Mach-O. Use this when you want a list of public re-exports from a `*.framework/Versions/A/*.framework/...` binary. |
| `nm-symbols` | `nm -gU` | Pull global defined symbols. Use `--filter=POSIX-REGEX` to narrow down to a family. |
| `strings-grep` | `strings` | Pull printable strings. Use `--pattern=REGEX` to narrow. Strings returned are base64-encoded to keep JSON safe for non-ASCII. |
| `class-dump-types` | `class-dump` | Pull `@interface` blocks. When `class-dump` is not installed (true on this host as of probe time), the wrapper emits `status=tool-not-installed` so callers can fall back to `nm` / `otool`. |
| `rea-call` | REA CLI | Pass-through to `npx -y rea-agents@6.4.0 …`. Defaults to `--format json`. Detects "unknown subcommand" stderr and emits `status=rea-cli-subcommand-not-found` so callers can classify the failure. |

## Output shape

```jsonc
{
  "tool": "otool" | "nm" | "strings" | "class-dump" | "rea",
  "binary": "<path-or-null>",
  "status": "ok" | "tool-not-installed" | "tool-failed" | "invocation-error" | "rea-cli's-subcommand-not-found",
  "exit_code": 0,
  "duration_ms": 12,
  "observations": { /* tool-specific */ },
  "error": "<message when status != ok>"
}
```

## Validators

- `scripts/lib/validate_evidence.py` — schema validator for
  `subsystems/**/evidence/*.json`. Stdlib-only so CI stays green without
  extra dependencies. Run from the repo root:

  ```bash
  python3 scripts/lib/validate_evidence.py .
  ```

  Exit `0` when all records conform; `1` otherwise. The CI job
  `.github/workflows/ci.yml` runs the same command on every push / PR.

- `scripts/lib/common.sh` — shared bash helpers (`parse_tool_args`,
  `emit_ok`, `emit_tool_missing`, `emit_tool_failed`, `assert_binary_present`).
  Source me; do not execute me.

## Development

- Wrappers must accept `bash <wrapper> --help` and exit 0.
- Wrappers must emit a valid `output-schema.json` envelope; even failure
  paths emit JSON, never plain text, so downstream `jq` stays usable.
- Wrappers must not invent tool names. If a tool is missing, emit
  `status=tool-not-installed` with an install hint and exit 0.
