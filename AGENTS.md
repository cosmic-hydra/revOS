# AGENTS.md — revOS agent team protocol

This file describes the agent roster that owns `cosmic-hydra/revOS` and the
rules every agent on the team follows. It is the contract the Curator / Harness
agent publishes at the start of every sprint and the contract every
subsystem agent agrees to by committing inside the harness.

## Five-agent roster

| Agent                | Role                                                         |
|----------------------|--------------------------------------------------------------|
| `curator`            | Owns the harness: schema, wrappers, CI, top-level docs, `_meta`. Lands exactly one harness commit per sprint. |
| `cf-types`           | Owns `subsystems/cf-types/`. Records CFString / CFArray / CFUUID-style boxed-type evidence. |
| `cf-runtime`         | Owns `subsystems/cf-runtime/`. Records CFRunLoop / CFSocket / CFNotification / CFPlugIn / CFStream evidence. |
| `libdispatch`        | Owns `subsystems/libdispatch/`. Records GCD queue / source / sync / group / IO evidence. |
| `foundation-bridge`  | Owns `subsystems/foundation-bridge/`. Records NSObject, KVC/KVO, autorelease, NSRunLoop bridge, NSCoder, and toll-free bridges. |

There are no other agents and no agent delegates to another. The Curator
publishes the harness; the four subsystem agents publish evidence records
into their own subtrees.

## File ownership map

| Path                                    | Owner                | Notes |
|-----------------------------------------|----------------------|-------|
| `README.md`, `LICENSE`, `docs/`         | `curator`            | Top-level docs only. |
| `evidence/schema.json`                  | `curator`            | Subsystem agents extend by adding records, never by editing the schema. |
| `scripts/lib/`, `scripts/bin/`          | `curator`            | Subsystem agents call these; do not modify. |
| `.github/workflows/`                    | `curator`            | CI gates. |
| `subsystems/_meta/`                     | `curator`            | Harness-only probes (e.g. `rea-doctor.json`). Subsystem agents MUST NOT write here. |
| `subsystems/cf-types/`                  | `cf-types`           | |
| `subsystems/cf-runtime/`                | `cf-runtime`         | |
| `subsystems/libdispatch/`               | `libdispatch`        | |
| `subsystems/foundation-bridge/`         | `foundation-bridge`  | |
| `subsystems/<area>/evidence/`           | owning agent         | Subsystem agents commit JSONs here. The directory `raw/` is gitignored. |
| `subsystems/<area>/notes/`              | owning agent         | Subsystem agents commit `.md` notes here. Do not state facts in notes without a paired evidence JSON. |

Subsystem agents MUST NOT edit another subsystem's JSON, even to "fix a typo".
If the typo matters, file a follow-up via the cross-reference array instead.

## Rebase-on-push policy

Every push follows the same dance:

```bash
git pull --rebase origin main
# (resolve conflicts if any)
git push
```

If `git push` reports a non-fast-forward, retry **once**:

```bash
git pull --rebase origin main
git push
```

If the second push attempt fails again, abort and report the exact failure.
Do not force-push. Do not push to a branch other than `main`.

## Evidence schema rules

Every claim a subsystem agent publishes MUST be backed by an evidence record
conforming to `evidence/schema.json`. The schema is enforced by
`scripts/lib/validate_evidence.py` (run in CI on every push / PR to `main`,
also runnable locally).

A record contains, at minimum:

- `subsystem` — one of `cf-types`, `cf-runtime`, `libdispatch`,
  `foundation-bridge`, `_meta`.
- `subject` — exact name of the symbol / type / function / constant /
  behavior being claimed about (no synonyms).
- `subject_kind` — one of `symbol`, `type`, `function`, `constant`,
  `behavior`.
- `source_artifact` — `{ path, sha256, format }` describing the binary or
  source the observation was made against. Hash is the SHA-256 of the file
  at observation time.
- `observation` — `{ tool, tool_invocation, summary, raw_output_excerpt }`
  with the exact wrapper invocation string.
- `claim` — falsifiable one-sentence statement.
- `claim_status` — `observed` (in the public Mach-O export table or
  assembly), `deduced` (reasoned from the opensource-apple mirror plus
  evidence), or `unknown`.
- `cross_reference` — `[]` of `{ upstream, label, url }` pointing at the
  opensource-apple / swift-corelibs mirror used to corroborate the claim.
- `confidence` — `0..1` numeric. `observed` symbols start at `0.9`,
  `deduced` start at `0.5`, `unknown` is `0.0`.
- `reproducer` — the shell command(s) that re-derive the record from
  `source_artifact`. Prefer `scripts/bin/*` wrappers.

## Honesty contract

The contract is the same as the project's verification policy:

1. **Do not fabricate API names.** Every name in `subject` must be defensible
   from the observation's `tool_invocation`.
2. **Cite the tool that observed the symbol.** `observation.tool` must
   match the script used. If you say "observed via `nm-symbols`", the
   `tool_invocation` must be a `nm-symbols` invocation.
3. **Mark unknowns as `unknown`**, never guessed. `claim_status` is the
   one place lying has the lowest cost — never pay it.
4. **No proprietary blobs in `raw_output_excerpt`.** Strip everything that
   could land a public commitment to a private Apple symbol's contents.
5. **Never reproduce header-only claims as `observed`.** A symbol that
   appears in `CFRunLoop.h` but is not in the framework's Mach-O export
   table is `deduced`, not `observed`.

## Workflow (per-sprint, per-subsystem)

1. Wait for the Curator to publish the harness commit on `main`.
2. From your own agent, work on a topic branch (`subsystems/<area>/<topic>`).
   Use `git pull --rebase origin main` to stay aligned.
3. Use `scripts/bin/<wrapper>` to produce raw JSON output.
4. Translate the JSON to one or more `subsystems/<area>/evidence/*.json`
   records conforming to `evidence/schema.json`.
5. Optionally write `subsystems/<area>/notes/<topic>.md` for synthesis that
   does **not** qualify as a single claim.
6. Locally run `python3 scripts/lib/validate_evidence.py` before pushing.
7. Land the commit with the conventional commit format
   `chore(<agent>): <description>` and push with the rebase-on-push policy
   above.

## Conventional commits

```
<type>(<agent>): <subject>
```

- `chore(<agent>)` for harness / scaffolding work
- `docs(<agent>)` for docs-only changes
- `evidence(<area>)` (not `evidence(_meta)`) when the commit is *only*
  evidence records
- `revert(<agent>)` for reverts

Forbidden types: `feat`, `fix` (we add evidence, never "features"). A
non-empty subject must come after the colon.
