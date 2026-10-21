# revOS Production Reimplementation — Design Spec

- **Date:** 2026-10-21
- **Status:** approved (rev 1 — all structural axes reworked after review)
- **Repo:** `cosmic-hydra/revOS`
- **Author:** mavis (root session), with the sprint-1 agent team

## 1. Goal

Ship a **working Linux-side implementation of the macOS Foundation / CoreFoundation /
libdispatch surfaces**, built from reverse-engineering evidence, with a published,
versioned, tested artifact.

"Prod ready" for revOS means all of:

1. **M1–M4 are implemented and green** (libdispatch, CoreFoundation core, Foundation
   bridge, CoreFoundation runtime).
2. **Three acceptance layers pass** — upstream suites, differential-vs-real-macOS,
   and evidence-bound traceability.
3. **CI is green on `main`** for every commit (currently it is not — see §2.3).
4. **The artifact is releasable** — semver tags, CHANGELOG, CI-gated releases.
5. **Every implementation cites an evidence record**, and every recorded gap was
   re-verified against current upstream before being implemented.

## 2. Starting state (measured, 2026-10-21)

### 2.1 Sprint-1 evidence is complete

`main` carries 76 evidence records across four subsystems, all schema-valid.

| Commit | Subsystem | Records | Notes |
|---|---|---|---|
| `564580e` | curator harness | 1 (`_meta`) | schema, 6 wrappers, CI |
| `9bcdcc8` | `cf-types` | 23 | boxed-type ABI, tagged-pointer symbols |
| `a60029b` | `foundation-bridge` | 14 | toll-free bridges, KVC/KVO, autorelease, NSCoder |
| `c93afd2` + `5550a7e` | `cf-runtime` | 26 | run loop, notification, socket, stream, plug-in |
| `8c01cd0` | `libdispatch` | 12 | GCD surface, OSS-vs-shipped deltas |

Validator: `python3 scripts/lib/validate_evidence.py .` → 76/76.

### 2.2 Key structural findings

- **CoreFoundation and Foundation are not Mach-O files on macOS 27.** Both framework
  paths are dangling symlinks; the real images live in the arm64e dyld shared cache.
  Consequently every `scripts/bin/*` wrapper fails against them with a misleading
  `binary not found`. The working path is `dyld_info -exports`, which reads the
  cache-resident `LC_DYLD_EXPORTS_TRIE` in place.
  - CF export dump: 3098 symbols, UUID `F4CE3D4A-29B8-3F98-A136-7089CEB27692`,
    arm64e, capture hash prefix `55c58b30c63b`.
- **libdispatch IS on disk** at `/usr/lib/system/introspection/libdispatch.dylib`,
  SHA-256 `0c6e2167fc596046a5c927ee72ed6fead1097ea5c952de0ad8f947f9a05d3286`.
- **`class-dump` is not in Homebrew.** No ObjC-class dumping tool is available.
  `class_copyMethodList` via the objc4 runtime is the working substitute.
- **The schema's `observation.tool` enum lacks `dyld_info`.** Three agents hit this
  and used `"other"`, which loses information. Fix in §6.

### 2.3 CI has been red on every commit

All five runs on `main` failed. Root cause: the `shellcheck` job passes
`scripts/bin/*` **and** `scripts/lib/*` to shellcheck, but `scripts/lib/validate_evidence.py`
is Python — shellcheck raises `SC1071` (a hard error). Secondary: `SC2034`
unused-variable warnings in `common.sh`, and the job's `||` fallback re-runs the
same command with the same excludes, so it cannot recover.

### 2.4 Upstream mirrors (pinned)

| Mirror | Pinned commit | Tag | Date | Upstream test suite? | License |
|---|---|---|---|---|---|
| `apple-oss-distributions/CF` | `dc54c6bb1c1e5e0b9486c1d26dd5bef110b20bf3` | `CF-1153.18` | 2015-06-23 | **No** (only `Examples/`) | `APPLE_LICENSE` (APSL) |
| `apple-oss-distributions/libdispatch` | `2361ffb78a76f7ee488cd052eb0bc5c767118bf9` | `libdispatch-1542.0.4` | 2025-10-04 | **No** (no test dir at this commit) | `LICENSE` (Apache-2.0) |
| `apple/swift-corelibs-foundation` | `b40c41e73612385c24be821bdfe95a67fdb157a5` | — | 2026-10-20 | **Yes** — `Tests/`, 137 files | `LICENSE` (Apache-2.0) |

**This is the most consequential measured fact in the spec:** only one of the three
upstreams ships a conformance suite. The differential-vs-macOS harness is therefore
not a third acceptance layer — for CF and libdispatch it is the **primary correctness
oracle**, and the upstream suites cover Foundation only.

### 2.5 Re-verification already invalidated part of our own evidence

Checked directly against `swift-corelibs-foundation` HEAD (`b40c41e7`):

| Claim | Verdict |
|---|---|
| KVC (`setValue:forKey:` / `valueForKey:`) absent | **Confirmed** — appears only in `NSExpression.swift` as a *consumer*, never implemented |
| KVO (`addObserver:forKeyPath:`) absent | **Confirmed** — zero hits for `NSKeyValueObserving` or `addObserver:forKeyPath:` across `Sources/Foundation/` |
| `automaticallyNotifiesObserversForKey:` absent | **Confirmed** — zero hits |
| `-getCFRunLoop` absent | **Correction required** — exists at `RunLoop.swift:126` as `internal func getCFRunLoop() -> CFRunLoop`, but on non-Darwin it is `internal func getCFRunLoop() -> Never` — it **traps**. The gap is "not public and fatals on Linux", not "absent" |

That last row exposes a gap class sprint 1 had no vocabulary for:
**present-but-traps** vs **absent** vs **present-but-private**. The capability
matrix (§5.3) is built to distinguish all three.

## 3. Decisions

### 3.1 Architecture — hybrid with a gap ledger

Per-gap route selection, recorded in an indexable artifact. No global rule.

- **shim** — additive gap implementable without touching upstream (new exported
  symbol, new method category, new module).
- **in-place-patch** — structural gap that must live inside upstream code
  (CF-Lite's `CFString.c` is the canonical case). Applied as a tracked patch
  series under `third_party/PATCHES/`, so upstream stays canonical and re-syncable.
- **from-scratch** — upstream cannot express the behaviour at all.

Rejected: *pristine upstream + shim only* (cannot host the CFString fast path);
*unconditional in-place patching* (upstream and our code become indistinguishable,
and a structural CFString patch is unreadable as a diff).

### 3.2 Milestones and gating

| Milestone | Scope | Depends on |
|---|---|---|
| **M1** | libdispatch on Linux: vendored OSS + proven deltas | — |
| **M2** | CoreFoundation core: CFType, CFString (incl. tagged-pointer fast path), CFArray, CFDictionary, CFSet, CFData, CFNumber, CFBoolean, CFDate, CFURL, CFError, CFUUID, CFEqual/Hash/Retain/Release | M1, Phase 0 |
| **M3** | Foundation bridge: NSObject, KVC, KVO, autorelease, NSRunLoop↔CFRunLoop, NSCoder/NSKeyedArchiver, 7 toll-free bridges | M2, Phase 0 |
| **M4** | CoreFoundation runtime: CFRunLoop, CFNotificationCenter, CFSocket, CFStream, CFPlugIn | M2, M1, Phase 0 |

Sequential because they are genuinely dependent: M2's CF needs GCD; M3's Foundation
needs CF; M4's run loop needs both. Parallelism happens **within** a milestone.

**Phase 0 runs in parallel with M1 and blocks M2/M3/M4.** M1's gaps are already
verified — the OSS mirror *is* the shipped source, so there is no shelf-life risk.
M2/M3/M4's gaps are exactly the ones with shelf life, so they wait for Phase 0.

Checkpoints between milestones are **non-blocking reports**, not interactive
approvals. The team works continuously; the user reads the report.

### 3.3 Tagged-pointer fidelity — both, split

- **Gate:** behavioural fidelity, defined precisely as:
  1. **API surface** — every symbol macOS exports for the covered types is
     exported by ours with the same signature.
  2. **Equality** — `CFEqual` agrees with macOS on every vector, including
     cross-type comparisons and `NULL` handling.
  3. **Hash relation, not hash value** — our `CFHash` must induce the *same
     equivalence relation* as macOS's (equal strings hash equally, unequal
     strings hash unequally). We do **not** gate on the numeric hash matching,
     because the underlying hash function is an implementation detail that may
     legitimately differ while the observable contract holds.
  4. **Copy semantics** — `CFCopy`/`CFRetain`/`CFRelease` produce the same
     observable value, aliasing behaviour and mutation independence.
  5. **Performance envelope** — no more than **2× slower** than the macOS
     runner across the vector corpus (a measured comparison, not a claim).
  6. **Error behaviour** — out-of-domain arguments, invalid selectors and
     over-release produce the same observable failure mode as macOS.
- **Tracked separately, not blocking:** the exact stolen-bit layout and inline-length
  cap. Phase 0 probes for it; whatever confidence the probe earns is recorded in the
  evidence corpus. Bit-exactness is a follow-on milestone, not a release blocker.

Rationale: a Linux-only library's `CFStringRef` is never dereferenced by real macOS
code, so bit-exactness buys no observable behaviour — and it is the single most
expensive unknown we hold.

### 3.4 Toolchain

- **C11 + CMake** for the library, the C-level Foundation bridge, the harness, and
  all vendored C sources (CF-Lite, libdispatch are both C).
- **Swift** only for the M3 Foundation shim module that extends
  swift-corelibs-foundation.
- Consequence: **M1, M2 and M4 need no Swift toolchain.** M3 introduces one.
- Target: **Linux x86_64 + arm64, glibc.** No musl, no non-glibc, no bare-metal.

### 3.5 M3 route

Vendor `swift-corelibs-foundation` unpatched; implement the proven gaps — KVC, KVO,
`+automaticallyNotifiesObserversForKey:`, and a public non-trapping
`getCFRunLoop()` — in our own Swift module (`impl/src/foundation/`) that upstream
never has to carry. Its 137 upstream tests become the Foundation conformance net.

### 3.6 Legal and honesty guardrails (carried forward, unchanged)

- Clean-room only: public headers + observed export tables + black-box behavioural
  probing. **No decompilation** — there is no Hopper/Ghidra/IDA in this environment
  and the spec keeps it that way.
- No proprietary byte ranges committed. Differential vectors capture *behaviour*,
  never internal memory layout.
- Every implementation cites an evidence record.
- No gap is implemented before re-verification (§4.2).
- The roadmap's existing anti-goals stand: no private Apple frameworks
  (`Apple80211`, `IOKit`), no circumvention of licensing/DMCA restrictions.

## 4. Phases

### 4.1 Phase 0a — Harness repair (blocking everything)

Small, bounded, and it unblocks every subsequent agent.

1. Fix the `shellcheck` CI job: shell-file-only globs, remove the broken `||`
   fallback, resolve `SC2034` in `common.sh`.
2. Add `scripts/bin/dyld-info-exports` — reads the export trie of a
   cache-backed image in place. This is the wrapper that three sprint-1 agents
   had to hand-roll.
3. Extend `evidence/schema.json` `observation.tool` enum with `dyld_info`.
4. Make the existing wrappers recognise a **cache-backed** image and report a
   distinct status (`cache-backed`) instead of the misleading `binary not found`.
5. Add `scripts/bin/capability-probe` — the Phase 0 probing primitive (§5.3).
6. Add `scripts/lib/validate_gap_ledger.py`.

### 4.2 Phase 0b — Re-verification and gap ledger (blocks M2/M3/M4)

For every sprint-1 record that asserts a **gap** (something upstream lacks, or
macOS has that upstream lacks):

1. Re-check the claim against the **current** upstream HEAD, not the pinned
   snapshot. Record `reverification.status` ∈ `still-open | closed-upstream |
   never-existed | drifted`.
2. Where the claim is wrong, **correct the original evidence record** and note the
   correction in the ledger. Sprint-1 evidence is not immutable when it was
   measured wrong — the `claim_status`/`confidence` fields are the contract, and a
   corrected record is more honest than a wrong one.
3. Produce one gap file per gap under `gap-ledger/gaps/`.

### 4.3 Phase 0c — Runtime probing (blocks M2 specifically)

The tagged-pointer bit layout is not derivable from an export table. It **is**
derivable by black-box probing of the genuine macOS CoreFoundation:

- `dlopen` real CoreFoundation, call `__CFStringCreateTaggedPointerString` with
  increasing lengths, observe the resulting pointer bit patterns.
- Same class of probe for every other API, producing the capability matrix.

This is behavioural observation — the same evidence category as the export tables
— and it needs no disassembler.

### 4.4 M1–M4

Per §3.2. Within a milestone: parallel agents on disjoint files, isolated
worktrees, one integrator merges to `main`.

## 5. Architecture

### 5.1 Repository layout

```
revOS/
├── README.md  AGENTS.md  LICENSE  CHANGELOG.md  VERSION
├── subsystems/                 # sprint-1 evidence (76 records) — unchanged
├── evidence/
│   ├── schema.json             # extended: +dyld_info in tool enum
│   └── probes/                 # runtime-probe captures (new)
├── gap-ledger/
│   ├── schema.json
│   ├── gaps/<gap-id>.json      # per-gap files (disjoint → parallel-safe)
│   └── index.json              # generated, not hand-edited
├── impl/
│   ├── CMakeLists.txt
│   ├── include/revos/          # public headers
│   ├── src/
│   │   ├── shim/               # additive macOS-27 gaps
│   │   ├── dispatch/           # M1
│   │   ├── cfcore/             # M2
│   │   ├── cfbridge/           # M4
│   │   └── foundation/         # M3 (Swift module)
│   └── tests/
│       ├── vectors/            # shared behavioural vector corpus
│       ├── macos/              # runner: dlopen genuine CF/Foundation
│       ├── linux/              # runner: our implementation
│       ├── conformance/        # our own CF + libdispatch suites
│       └── upstream/           # swift-corelibs-foundation tests
├── third_party/
│   ├── libdispatch/  CF/  swift-corelibs-foundation/
│   ├── PATCHES/                # patch series for in-place gaps
│   └── LICENSES/               # per-vendor licence copies
├── tools/
│   ├── differ.py               # differential comparator
│   ├── license_check.py
│   └── generate_capability_matrix.py
├── docs/  ROADMAP.md  superpowers/specs/
└── .github/workflows/ci.yml
```

**Why per-gap files rather than one `gap-ledger.json`:** parallel agents writing
disjoint files never contend on an index. Sprint 1 already demonstrated the
failure mode of shared mutable state (agents clobbering each other's git index
in a shared working tree). `index.json` is generated from the per-gap files by
the validator, so it can never drift.

### 5.2 The gap ledger — the central artifact

The bridge between the evidence world and the code world. One file per gap:

```json
{
  "gap_id": "cf-string-tagged-pointer",
  "subsystem": "cf-types",
  "gap_statement": "macOS 27 exports a CFString tagged-pointer fast path absent from CF-Lite 1153.18",
  "evidence_refs": ["subsystems/cf-types/evidence/cfstringcreatetaggedpointerstring-55c58b30c63b.json"],
  "upstream": {
    "repo": "apple-oss-distributions/CF",
    "pinned_commit": "dc54c6bb1c1e5e0b9486c1d26dd5bef110b20bf3",
    "pinned_tag": "CF-1153.18",
    "verified_at": "2026-10-21",
    "head_commit": "<verified against HEAD during Phase 0b>",
    "head_verified_at": "<…>"
  },
  "reverification": {
    "status": "still-open | closed-upstream | never-existed | drifted",
    "method": "command(s) run against upstream HEAD",
    "result": "…"
  },
  "route": "shim | in-place-patch | from-scratch",
  "implementation_ref": { "file": "impl/src/cfcore/CFStringTagged.c", "symbol": "…", "commit": "<sha>" },
  "test_refs": ["impl/tests/vectors/cfstring-tagged.jsonl", "impl/tests/conformance/…"],
  "status": "open | in-progress | implemented | verified | dropped"
}
```

Invariants, enforced by `validate_gap_ledger.py`:

1. Every `evidence_refs[]` entry resolves to a real, schema-valid evidence record.
2. Every gap with `status != "open"` has a non-empty `reverification.result`.
3. Every gap with `status ∈ {implemented, verified}` has an `implementation_ref` and
   at least one `test_refs[]` entry.
4. `route` and `status` are consistent with the artifact the route implies
   (a `shim` gap must not have an entry under `third_party/PATCHES/`).
5. A gap whose `reverification.status == "closed-upstream"` must have
   `status == "dropped"` — **we do not implement gaps that no longer exist.**

### 5.3 The differential harness — the primary oracle

One corpus, two runners, one differ.

- **Vector corpus** (`impl/tests/vectors/*.jsonl`): behavioural inputs and expected
  observations. Captures return values, equality, hash values, error codes, and
  error-domain behaviour. **Never internal memory layout, never proprietary bytes.**
  Versioned; each vector file names the evidence records that motivated it.
- **macOS runner** (`impl/tests/macos/`): a single C binary that `dlopen`s the
  genuine CoreFoundation and Foundation and emits canonical JSONL.
- **Linux runner** (`impl/tests/linux/`): same corpus against our implementation,
  same canonical JSONL.
- **Differ** (`tools/differ.py`): compares the two JSONL files, classifies each
  mismatch, writes a report. A mismatch is a **bug report with a reproducible
  vector**.
- **Capability matrix** (`tools/generate_capability_matrix.py`): for every exported
  API, record macOS status vs Linux status as `works | traps | missing | private`.
  Generated by the same probing infrastructure, and shipped as a product artifact —
  it is the "what actually works on Linux" map.

The harness is also the **Phase 0c RE tool**: probing genuine macOS is exactly
how the tagged-pointer layout gets observed. One mechanism, two jobs.

### 5.4 Acceptance — three layers

| Layer | Mechanism | Covers | Notes |
|---|---|---|---|
| **1 — Upstream suites** | swift-corelibs-foundation's 137 tests | Foundation (M3) only | CF-Lite and libdispatch ship no suite; see §2.4 |
| **2 — Differential vs real macOS** | vector corpus → macOS runner → Linux runner → differ | M1, M2, M4 and M3's C-level surface | **Primary oracle.** Runs in CI via a macOS artifact job |
| **3 — Evidence-bound** | every test cites the evidence record that motivated it | all | Enforced by a test-lint that fails on an uncited test |

Layer 1 is supplemented by our own `impl/tests/conformance/` suites for CF and
libdispatch, since upstream provides none.

### 5.5 CI and release

Jobs on every push to `main` and every PR:

| Job | Runner | Purpose |
|---|---|---|
| `shellcheck` | ubuntu-latest | shell files only; no broken fallback |
| `validate-evidence` | ubuntu-latest | 76+ records against the schema |
| `validate-gap-ledger` | ubuntu-latest | the 5 invariants in §5.2 |
| `license-check` | ubuntu-latest | every vendored tree's licence recorded in `third_party/LICENSES/` |
| `build` | ubuntu-24.04 + ubuntu-24.04-arm | CMake build, x86_64 + arm64 |
| `conformance` | ubuntu-latest | our CF + libdispatch suites |
| `upstream-foundation` | ubuntu-latest + Swift toolchain | swift-corelibs-foundation tests |
| `differential-macos` | macos-15 | runs the macOS runner, uploads `vectors-macos.jsonl` |
| `differential` | ubuntu-latest | downloads the artifact, runs the differ, fails on mismatch (with an explicit allowlist for known differences) |
| `capability-matrix` | ubuntu-latest | regenerates the matrix, fails on drift |

Release: semver in `VERSION`, `CHANGELOG.md`, GitHub releases with artifacts.
A tag release requires green CI on the tagged SHA. A release is only cut when
all four milestones are `verified` in the gap ledger.

### 5.6 Agent topology

- **One git worktree per agent.** Sprint 1's `cf-runtime` agent correctly diagnosed
  that all agents sharing one working tree clobber each other's git index; that
  cost one failed commit and nearly a lost one. Worktrees make the index
  per-agent.
- **Within a milestone:** parallel agents, disjoint file ownership, each on its own
  branch off `main`, integrated by one agent that merges to `main`.
- **Bounded briefs.** Each agent gets an explicit token/time budget and a
  "write records in one batch → validate → commit → report" discipline. Sprint 1
  lost two agents to a 300 s LLM-event timeout and one to a token-plan ceiling;
  briefs now say so explicitly.
- **Checkpoints are reports, not gates.** The team proceeds through M1→M4; the
  user gets a milestone report and may interject.

## 6. Error handling and failure modes

| Failure | Detection | Response |
|---|---|---|
| Gap no longer exists upstream | Phase 0b re-verification | `status: dropped`, record the correction, implement nothing |
| Differential mismatch | differ job | Block the release; file as a bug with a reproducible vector |
| Upstream re-sync breaks a patch | `third_party/PATCHES` fails to apply | Re-base the patch series; re-run the affected milestone's suites |
| macOS runner unavailable in CI | artifact job missing | Fall back to a known-good `vectors-macos.jsonl` pinned as an artifact, flagged as stale in the report — never silently skip |
| Agent timeout / token ceiling | task status | Work is committed per agent; the integrator re-runs only the unfinished portion |
| Evidence validator fails | CI | Block the commit; a malformed record is worse than a missing one |
| Capability-matrix drift | CI | Fail the job; the matrix is a product artifact and must be regenerated deliberately |

## 7. Testing strategy

- **Vector corpus** is the contract between layers. It is versioned, each vector
  names its motivating evidence, and it is the input to both runners.
- **Differential** is the default oracle for anything with a macOS counterpart.
- **Upstream suites** run unmodified against our build where they exist.
- **Our conformance suites** cover what upstream does not: CF boxed types, CF
  runtime, libdispatch surface.
- **Evidence-bound lint** fails any test that does not cite an evidence record.
- **Known-difference allowlist** is explicit, reviewed, and never grows silently.

## 8. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Gap-closing premise partly wrong — upstream moved on | High | Phase 0b re-verification before any implementation; §2.5 already caught one wrong claim |
| Tagged-pointer bit layout not cleanly observable | Medium | Bit-exactness is explicitly non-blocking (§3.3); behavioural gate is achievable regardless |
| libdispatch has no upstream test suite | Medium | Our own conformance suite + differential harness |
| Swift toolchain friction on Linux for M3 | Medium | Swift needed only for M3; M1/M2/M4 are pure C |
| Token-plan ceiling truncates the run | High | Milestone checkpoints, bounded briefs, per-agent commits so partial work is never lost |
| Differential harness flakiness (macOS runner nondeterminism) | Medium | Canonicalise outputs; pin the corpus; allowlist known differences explicitly |
| Vendored OSS licence bookkeeping slips | Low | `license-check` CI job; `third_party/LICENSES/` |

## 9. Non-goals

- Shipping a bit-exact reproduction of Apple's internal tagged-pointer layout
  (tracked as a follow-on, not a release gate).
- Reverse engineering private Apple frameworks (`Apple80211`, `IOKit`).
- AppKit / UI surface, XPC, launchd — M5+, after M1–M4 are green.
- A macOS-on-Linux compatibility layer (this is a *library*, not an OS port).
- Any proprietary byte range in the repository.

## 10. Definition of done

revOS is prod ready when **all** of the following hold:

1. `main` is green: every CI job in §5.5 passes.
2. All four milestones are `verified` in the gap ledger — no gap is `open`.
3. No gap with `reverification.status == "closed-upstream"` is implemented.
4. The differential differ reports zero unexplained mismatches.
5. swift-corelibs-foundation's upstream suite passes against our build.
6. Every test in `impl/tests/` cites at least one evidence record.
7. `VERSION`, `CHANGELOG.md` and a tagged release exist.
8. The README states plainly what the library does and does not do, including the
   behavioural-fidelity-vs-bit-exactness boundary, and names the evidence
   records that justify each implemented gap.

## 11. Working agreement

The user asked to stop being asked multiple questions. Accordingly:

- Design decisions at this level are made by the agent team and recorded here.
- Milestone checkpoints are **reports**, not approval requests.
- The user may interject at any time; interjections preempt the plan.

## 12. Planning decomposition

This spec describes the whole programme; it is **not** a single implementation
plan. A plan spanning M1–M4 would be unactionable — four milestones, a vendoring
strategy, a new test harness, a CI re-architecture and a release process.

The implementation plan is therefore authored **per phase**, in dependency order,
each one a complete plan → implement → verify cycle:

| Plan | Scope | Gate |
|---|---|---|
| **Plan 1** | Phase 0a — harness repair (§4.1) | CI green on `main`, `dyld_info` in the schema, cache-backed detection working |
| **Plan 2** | Phase 0b — re-verification + gap ledger (§4.2) | every gap has a `reverification` result; corrected evidence records committed |
| **Plan 3** | Phase 0c — probing infrastructure + capability matrix (§4.3, §5.3) | macOS runner produces canonical JSONL; matrix generated |
| **Plan 4** | M1 — libdispatch (§4.4) | M1 green on all three acceptance layers |
| **Plan 5** | M2 — CoreFoundation core | M2 green |
| **Plan 6** | M3 — Foundation bridge | M3 green |
| **Plan 7** | M4 — CoreFoundation runtime | M4 green |
| **Plan 8** | Release engineering | semver release cut against the §10 definition of done |

Plans 1–4 are authored now, in that order. Plans 5–8 are authored after the
preceding plan lands, because their content depends on what the earlier plans
actually produce — in particular M2's implementation shape depends on what the
Phase 0c probe reveals about the tagged-pointer layout.

**Plan 1 is deliberately first and deliberately small.** It is bounded, it has no
dependencies, and it repairs a harness that is currently red — meaning the first
thing this programme produces is a trustworthy foundation to build on.

## 13. Provenance

- Sprint-1 evidence: 76 records, commits `564580e`..`8c01cd0`.
- Re-verification data in §2.5 was gathered directly from the cached mirrors under
  `/Users/vaithianathan/revOS-work/cache/` on 2026-10-21.
- No decompilation was performed. No disassembler was installed. All observations
  are export tables, symbol tables, upstream source, or black-box behaviour.
