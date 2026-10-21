# revOS — A public, evidence-first reverse-engineering effort for macOS Foundation / CoreFoundation / libdispatch

revOS catalogues the **public** Mach-O ABI surface of Apple's CoreFoundation,
Foundation, and libdispatch frameworks for the purpose of writing compatible
shims, re-implementations, and educational tooling. The project is organised
as a sprint-driven agent team: each sprint produces a single new agent roster,
each agent lands evidence-backed claims in its own subsystem subtree, and a
single Curator / Harness agent owns the scaffold this README describes.

> **Scope of this commit (sprint 1, harness only).** This commit does *not*
> disassemble any binary. It only establishes the harness: directory layout,
> evidence schema, scripts/bin/* wrappers, CI gates, and the four empty
> subsystem subtrees that the four subsystem agents will fill in.

## Scope (sprint 1)

Sprint 1 is run by five agents. The four subsystem agents will produce
`subsystems/<area>/evidence/*.json` records; only the Curator / Harness agent
(this commit) owns the harness.

| Agent | Subsystem | Owned subtree |
|---|---|---|
| `cf-types` | CoreFoundation boxed-type ABI (CFString, CFArray, …, CFUUID) | `subsystems/cf-types/` |
| `cf-runtime` | CoreFoundation runtime (CFRunLoop, CFNotification, CFSocket, CFPlugIn, CFStream) | `subsystems/cf-runtime/` |
| `libdispatch` | GCD queue / source / sync / group / semaphore / IO primitives | `subsystems/libdispatch/` |
| `foundation-bridge` | Foundation ↔ CoreFoundation toll-free bridges, KVC/KVO, autorelease, NSRunLoop | `subsystems/foundation-bridge/` |
| `curator` | This scaffold, the harness wrappers, the schema, the CI job, the REA probe | `subsystems/_meta/`, `evidence/`, `scripts/`, `.github/`, top-level docs |

Each subsystem agent acts only inside its own subtree and never edits another
agent's evidence JSONs. Cross-boundary facts are referenced via the
`cross_reference` array (see `evidence/schema.json`).

## Harness

Everything below the harness is built around an **evidence schema**:

- `evidence/schema.json` — canonical JSON-Schema 2020-12 definition every
  evidence record must satisfy. Required fields: `subsystem`, `subject`,
  `subject_kind`, `source_artifact`, `observation`, `claim`,
  `claim_status`, `cross_reference`, `confidence`, `reproducer`.
- `subsystems/<area>/evidence/*.json` — JSON evidence records filled in by
  each subsystem agent.
- `scripts/bin/` — executable wrappers (`otool-exports`, `nm-symbols`,
  `strings-grep`, `class-dump-types`, `rea-call`) that emit JSON envelopes
  conforming to `scripts/bin/output-schema.json`.
- `scripts/lib/validate_evidence.py` — the schema validator run in CI; also
  invokable locally (`python3 scripts/lib/validate_evidence.py`).
- `.github/workflows/ci.yml` — `lint-shell` and `validate-evidence` jobs.
- `subsystems/_meta/` — the Curator's private area. The first record in
  `subsystems/_meta/evidence/rea-doctor.json` is the harness's only first-day
  piece of evidence (a probe of the REA CLI).

Subsystem agents extend the harness by adding evidence records; they do NOT
extend the schema, the wrappers, or the CI job without Curator coordination.

## Tooling

Available on the host:

- `otool` — Mach-O header / linked-lib / export inspection.
- `nm` — symbol table (`-gU` for global defined symbols).
- `strings` — printable string extraction.
- `class-dump` — Objective-C class layout. Not currently installed on this
  host; the `class-dump-types` wrapper emits `status=tool-not-installed`
  when missing and *does not* fail the CI run.
- `dsymutil`, `dtrace` — for deeper symbol resolution and runtime probes.

REA (Reverse-Engineer-Anything) is wired in via `scripts/bin/rea-call`:

- **Entry point**: `npx -y rea-agents@6.4.0 …` (or the wrapper
  `scripts/bin/rea-call <args…>`).
- **REA CLI honesty contract**: in this runtime, `npx -y rea-agents@6.4.0 mcp
  --help` only exposes two subcommands, `add` and `doctor`. The 170 tools
  listed by `rea mcp doctor` are *registered* against the MCP server, but
  the REA CLI offers them at the **top level** (`rea analyze`,
  `rea inspect`, `rea decompile`, etc.). See
  `subsystems/_meta/evidence/rea-doctor.json` for the probe record. The
  brief's reference to `npx -y rea-agents@6.4.0 mcp <subcmd>` is therefore
  too narrow; `scripts/bin/rea-call` accepts the full REA argv and defaults
  to `--format json`.
- **Decompilation caveat**: REA's `decompile`, `analyze`, `inspect` flow is
  still approximate — there is **no Ghidra, Hopper, IDA, or radare2** on
  this host (verified by `command -v`). Reverse engineering is therefore
  constrained to symbol/string extraction from public Mach-O exports plus
  opensource-apple mirror comparison.

### Supported REA probe results (cached from sprint-1 probe)

```jsonc
{
  "healthy": true,
  "server": { "name": "rea", "version": "6.4.0", "protocol_version": "2025-11-25" },
  "inventory": { "tools": { "expected": 170, "observed": 170 } },
  "identity": { "catalog_digest": "85d80276…f556fa5cf734eef768cc7d72a" }
}
```

## Layout

```
.
├── README.md                              this file (project front page)
├── AGENTS.md                              agent team protocol & ownership
├── LICENSE                                project licence (MIT-equivalent)
├── docs/
│   └── ROADMAP.md                         subsystem plan + future subsystems
├── evidence/
│   ├── schema.json                        canonical evidence record schema
│   └── (subsystem agents append here)     future evidence records (cross-tree)
├── scripts/
│   ├── README.md                          wrapper usage docs
│   ├── lib/
│   │   ├── common.sh                      shared helpers for wrappers
│   │   └── validate_evidence.py           stdlib JSON-Schema validator
│   └── bin/
│       ├── otool-exports                  Mach-O linked-lib + export wrapper
│       ├── nm-symbols                     nm wrapper, --filter=REGEX
│       ├── strings-grep                   strings wrapper, --pattern=
│       ├── class-dump-types               class-dump wrapper, --arch=
│       ├── rea-call                       REA CLI pass-through wrapper
│       └── output-schema.json             shape every wrapper emits
├── subsystems/
│   ├── _meta/                             Curator only — harness probes
│   │   └── evidence/rea-doctor.json       sprint-1 probe record
│   ├── cf-types/                          cf-types agent subtree
│   ├── cf-runtime/                        cf-runtime agent subtree
│   ├── libdispatch/                       libdispatch agent subtree
│   └── foundation-bridge/                 foundation-bridge agent subtree
└── .github/workflows/ci.yml               lint-shell + validate-evidence
```

## Limitations / non-goals

- **No Ghidra / Hopper / IDA / radare2.** Decompilation relies on REA only,
  and REA's decompiler is approximate. Pure symbol / string reconstruction.
- **Public surface only.** We do not reverse Apple private frameworks
  (`Apple80211`, `IOKit`, …) and we do not lift private symbol exports.
- **No clean-room copy for piracy.** This project is documentation +
  shim-and-reimplementation scaffolding. It is *not* a clean-room copy of
  any closed-source Apple code; the cross_reference pointers are to
  opensource-apple mirrors only.
- **No Apple EULA / DMCA breach.** We never publish proprietary byte ranges
  or decompiled Apple private code. Where `raw_output_excerpt` is captured
  it is truncated to ≤1 KB and stripped of any incidental proprietary
  fragments.
- **sprint 1 is harness-only.** No claim about any public API is made by
  this commit; subsystem agents will produce such claims in subsequent
  commits.

## Verifying locally

```bash
bash scripts/bin/otool-exports --help
bash scripts/bin/nm-symbols --help
python3 scripts/lib/validate_evidence.py
```

## License

MIT (see `LICENSE`). Reverse-engineering conclusions, evidence records, and
the harness code in this repository are made available for research and
shim authoring purposes; consult Apple's published licenses and the
opensource-apple mirrors cited in each evidence record before redistributing.
