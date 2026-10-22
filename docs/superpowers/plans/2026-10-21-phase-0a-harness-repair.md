# Phase 0a — Harness Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make revOS's harness trustworthy — CI green on `main`, the dyld-shared-cache blindness fixed, and the gap-ledger machinery in place — so that every later phase builds on a foundation that actually works.

**Architecture:** Seven bounded tasks, each independently testable and committable. Task 1 repairs CI and the real warnings it surfaces. Task 2 adds a `dyld_info -exports` wrapper, which is the only way to read the export trie of a cache-backed image on macOS 27. Task 3 teaches the existing wrappers to detect cache-backed binaries and fall back to `dyld_info` automatically, so `nm-symbols` works on CoreFoundation. Task 4 extends the evidence schema with `dyld_info` and adds a `capability-probe` primitive. Task 5 makes the wrapper default to the host-native slice, adds a corpus slice-attribution audit tool, and corrects the wrong-slice addresses that Task 2's review exposed in the shipped libdispatch evidence. Task 6 adds the gap-ledger schema and its validator. Task 7 wires everything into CI, adds a local CI runner, and lays down release scaffolding.

**Tech Stack:** Bash 3.2 (macOS default) + `jq`, Python 3 (stdlib only), `shellcheck`, GitHub Actions, CMake (later phases).

## Global Constraints

- **Shell is Bash 3.2-compatible.** macOS ships `/bin/bash` 3.2. Do not use associative arrays, `mapfile`, or `&>>`.
- **Python is stdlib-only.** `scripts/lib/validate_evidence.py` currently imports only `json`, `pathlib`, `re`, `sys`. Do not add third-party dependencies.
- **`jq` is a hard dependency** of every wrapper. It is already used in all six wrappers; keep using it for JSON construction rather than hand-rolled string concatenation.
- **Every wrapper emits exactly one JSON object on stdout**, conforming to `scripts/bin/output-schema.json`. No stray output, no banner text.
- **Every wrapper's `--help` exits 0 and prints usage to stdout.**
- **Commit format:** `chore(harness): …` for Task 1 and Task 7, `feat(harness): …` for Tasks 2–6. Never `feat(<subsystem>):` — subsystem commits belong to subsystem agents.
- **Stage only the files named in the task.** Never `git add -A`. A parallel agent may be working in the same tree; verify with `git diff --cached --name-only` before every commit.
- **No file moves in this phase.** `scripts/bin/output-schema.json` and `scripts/lib/validate_evidence.py` stay exactly where they are; CI selects shell files by shebang instead of by directory glob.
- **Do not modify anything under `subsystems/`.** Those 76 records are evidence and are owned by the subsystem agents.
- **The arm64e dyld shared cache is arm64e-only.** `dyld_info -arch x86_64 -exports <cache-backed path>` still reports the `arm64e` slice. The arch recorded in observations must be parsed from the `dyld_info` output header, never from the requested `--arch` flag.

---

## File Structure

| Path | Responsibility | Action |
|---|---|---|
| `.github/workflows/ci.yml` | CI job definitions | Modify — Tasks 1, 6 |
| `scripts/lib/common.sh` | Shared wrapper helpers | Modify — Tasks 1, 3 |
| `scripts/bin/nm-symbols` | `nm -gU` symbol dump | Modify — Tasks 1, 3 |
| `scripts/bin/otool-exports` | `otool -L` / `-Iv` dump | Modify — Task 3 |
| `scripts/bin/rea-call` | REA CLI passthrough | Modify — Task 1 |
| `scripts/bin/dyld-info-exports` | Export-trie reader that works on cache-backed images | Create — Task 2, Modify — Task 5 |
| `scripts/bin/capability-probe` | Per-symbol capability probe (works / traps / missing / private) | Create — Task 4 |
| `scripts/bin/revos-ci` | Local mirror of the CI job list | Create — Task 7 |
| `evidence/schema.json` | Evidence record JSON-Schema | Modify — Task 4 |
| `scripts/lib/audit_slice_attribution.py` | Attributes every cited corpus address to a slice | Create — Task 5 |
| `subsystems/libdispatch/evidence/` | Sprint-1 libdispatch evidence; wrong-slice addresses corrected | Modify — Task 5 |
| `gap-ledger/schema.json` | Gap record JSON-Schema | Create — Task 6 |
| `scripts/lib/validate_gap_ledger.py` | Gap-ledger validator | Create — Task 6 |
| `scripts/lib/validate_wrapper_output.py` | Validates wrapper envelopes against the wrapper-output schema | Create — Task 7 |
| `VERSION` | Semver string, one line | Create — Task 7 |
| `CHANGELOG.md` | Release notes | Create — Task 7 |
| `AGENTS.md` | Agent protocol | Modify — Task 7 |
| `README.md` | Project front page | Modify — Task 7 |

---

### Task 1: Repair the CI shellcheck job and the warnings it surfaces

**Files:**
- Modify: `scripts/bin/nm-symbols:56-66` (dead array block)
- Modify: `scripts/bin/rea-call:93-97` (unused `rc`)
- Modify: `scripts/lib/common.sh:79-81` and `:141-155` (SC2034)
- Modify: `.github/workflows/ci.yml` (job body)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: a green `shellcheck` CI job; `scripts/lib/common.sh` keeps its existing public helpers (`parse_tool_args`, `emit_ok`, `emit_tool_missing`, `emit_tool_failed`, `assert_binary_present`) unchanged in signature.

- [ ] **Step 1: Reproduce the failure locally**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
shellcheck --severity=warning --exclude=SC1091,SC2154,SC2086 scripts/bin/* scripts/lib/*
```
Expected: FAIL. Output includes `SC1071` for `scripts/lib/validate_evidence.py`, `SC2148`/`SC1070`/`SC1141` for `scripts/bin/output-schema.json`, `SC2178`/`SC2128` in `scripts/bin/nm-symbols`, `SC2034` in `scripts/bin/rea-call` and twice in `scripts/lib/common.sh`.

- [ ] **Step 2: Remove the dead array block in `scripts/bin/nm-symbols`**

The block at lines 56–66 builds a `filtered` array that is never read — line 69 immediately reassigns `filtered` as a string, which is what triggers `SC2178` and `SC2128`. Delete the array entirely and rename the string variable so the two uses cannot collide again.

Replace:
```bash
# Extract filter (if any)
filter=""
filtered=()
i=0
for arg in "$@"; do
  if [[ "$arg" == --filter=* ]]; then filter="${arg#--filter=}"; fi
  filtered[$i]="$arg"
  i=$((i+1))
done
```
with:
```bash
# Extract filter (if any). WRAPPER_OPTS already captured unknown flags, so we
# only need the value here. Note: no array is built — the symbol table is a
# string, not a list, and reusing one name for both shapes trips shellcheck
# SC2178/SC2128.
filter=""
for arg in "$@"; do
  if [[ "$arg" == --filter=* ]]; then filter="${arg#--filter=}"; fi
done
```
And replace the two later uses of `filtered` (the `awk` assignments and the `-n` test) with the new name `symbol_lines`:
```bash
symbol_lines=$(printf '%s\n' "$raw" | awk '
  NF >= 3 && $2 ~ /^[A-Za-z]$/ && $1 ~ /^[0-9a-fA-F]+$/ { print $1, $2, $3 }
')
if [[ -n "$filter" ]]; then
  symbol_lines=$(printf '%s\n' "$symbol_lines" | awk -v re="$filter" '$3 ~ re { print }')
fi

# Count safely.
if [[ -n "$symbol_lines" ]]; then
  total=$(printf '%s\n' "$symbol_lines" | grep -c '' || true)
else
  total=0
fi
```
and
```bash
if [[ -n "$symbol_lines" ]]; then
  symbols_json=$(printf '%s\n' "$symbol_lines" \
    | jq -Rn '[inputs | split(" ") | .[0] as $addr | .[1] as $kind | .[2] as $name
              | {address: $addr, kind: $kind, name: $name, section: null}]')
else
  symbols_json="[]"
fi
```

- [ ] **Step 3: Remove the unused `rc` in `scripts/bin/rea-call`**

Replace:
```bash
if ! npx -y rea-agents@6.4.0 "$@" >"$tmp_out" 2>"$tmp_err"; then
  rc=$?
```
with:
```bash
if ! npx -y rea-agents@6.4.0 "$@" >"$tmp_out" 2>"$tmp_err"; then
```
(`$?` is not read anywhere in that branch; the exit code is emitted as the literal `1` in the JSON envelope.)

- [ ] **Step 4: Silence the two genuine SC2034 false positives in `scripts/lib/common.sh`**

`BINARY` and `BIN_VALID` *are* consumed — by the wrappers that `source` this file — but shellcheck cannot see across the `source` boundary. Disable the check at the two assignment sites with an explanation, rather than excluding SC2034 repo-wide (which would hide real dead assignments later).

Replace line 80:
```bash
    BINARY="${POSITIONAL[0]}"
```
with:
```bash
    # shellcheck disable=SC2034  # consumed by the sourcing wrapper, not here
    BINARY="${POSITIONAL[0]}"
```
Replace line 153:
```bash
  BIN_VALID="ok"
```
with:
```bash
  # shellcheck disable=SC2034  # consumed by the sourcing wrapper, not here
  BIN_VALID="ok"
```

- [ ] **Step 5: Rewrite the `shellcheck` CI job body**

In `.github/workflows/ci.yml`, replace the `run:` block of the `lint-shell` job (the whole block from `run: |` through the end of the `||` fallback) with exactly this:

```yaml
      - name: Run shellcheck
        # Select by shebang, not by directory glob: scripts/bin/ also holds
        # output-schema.json and scripts/lib/ also holds validate_evidence.py.
        # Both are non-shell and make shellcheck raise hard errors (SC2148,
        # SC1070, SC1071). Selecting by bash shebang keeps this list correct as
        # wrappers are added.
        run: |
          set -euo pipefail
          SHELL_FILES=$(grep -rlI '^#!/usr/bin/env bash' scripts/ | sort)
          echo "Shell files to check:"
          echo "$SHELL_FILES"
          # SC1091: sourced files are read at runtime, not statically.
          shellcheck --severity=warning --exclude=SC1091 $SHELL_FILES
```

There is no fallback branch. If shellcheck reports anything, the job fails — that
is the point of the gate.

- [ ] **Step 6: Verify shellcheck passes locally**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
SHELL_FILES=$(grep -rlI '^#!/usr/bin/env bash' scripts/ | sort)
shellcheck --severity=warning --exclude=SC1091 $SHELL_FILES
```
Expected: no output, exit code 0. Confirm the selection is exactly six files:
```bash
echo "$SHELL_FILES" | wc -l   # expect 6
```

- [ ] **Step 7: Verify the wrappers still work after the `nm-symbols` refactor**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
bash scripts/bin/nm-symbols --filter='^_pthread' /usr/lib/system/libsystem_pthread.dylib | jq '.status, .observations.total'
```
Expected: `"ok"` and `observations.total` of **139**.

`libsystem_pthread.dylib` exports 209 symbols in total, of which 139 are
`_pthread*` and **none** are `_CF*`. A filter of `^_CF` therefore correctly
returns 0 — that is the filter matching nothing, not a wrapper fault. Use
`^_pthread` to get a non-zero count from this control binary.

- [ ] **Step 8: Commit**

```bash
cd /Users/vaithianathan/revOS-work/revOS
git add .github/workflows/ci.yml scripts/bin/nm-symbols scripts/bin/rea-call scripts/lib/common.sh
git diff --cached --name-only
git commit -m "chore(harness): repair shellcheck CI job and the warnings it surfaced

The lint-shell job passed scripts/bin/* and scripts/lib/* to shellcheck, but
those directories also contain output-schema.json and validate_evidence.py.
shellcheck raised hard errors on both (SC2148, SC1070, SC1141, SC1071), and
the job's '||' fallback re-ran the identical command with identical excludes,
so it could never recover. CI has been red on every commit since 564580e.

- CI now selects shell files by bash shebang, not by directory glob.
- Removed the dead array block in nm-symbols that shadowed a string variable
  (SC2178, SC2128) and renamed the variable so the two shapes cannot collide.
- Removed an unused rc capture in rea-call (SC2034).
- Scoped SC2034 disables to the two common.sh assignments that sourcing
  wrappers consume, rather than excluding SC2034 repo-wide."
# Do not push. The controller reviews this branch and merges it to `main`
# after the task review passes.
```

---

### Task 2: Add the `dyld-info-exports` wrapper

**Files:**
- Create: `scripts/bin/dyld-info-exports`

**Interfaces:**
- Consumes: `parse_tool_args`, `emit_ok`, `emit_tool_missing`, `emit_tool_failed`, `assert_binary_present` from `scripts/lib/common.sh` (unchanged by this task).
- Produces: `scripts/bin/dyld-info-exports [--filter=REGEX] [--arch=ARCH] <binary-path>` emitting `observations.arch` (string), `observations.exports` (array of `{address, name}`), `observations.total` (integer). Task 3 reuses this wrapper's parsing via `common.sh`.

**Background you need:** On macOS 27, `/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation` is a **dangling symlink** — `test -e` is false, `test -L` is true. `nm` and `otool` cannot open it ("No such file or directory"). `dyld_info -exports` *can*, because the image is resident in the arm64e dyld shared cache.

`dyld_info -exports` output format:
```
/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation [arm64e]:
    -exports:
        offset      symbol
        0x0013432C  _CFAbsoluteTimeAddGregorianUnits
```
Export lines have **two spaces** between offset and symbol. The arch appears in the header line, in square brackets.

- [ ] **Step 1: Write the wrapper**

Create `scripts/bin/dyld-info-exports` with content:

```bash
#!/usr/bin/env bash
# scripts/bin/dyld-info-exports
#
# Read the export trie of a Mach-O image with `dyld_info -exports`.
#
# Why this exists: on macOS 27 the system frameworks (CoreFoundation,
# Foundation) are NOT Mach-O files on disk — the framework path is a dangling
# symlink and the real image is resident in the arm64e dyld shared cache.
# `nm` and `otool` cannot open such a path ("No such file or directory").
# `dyld_info -exports` reads the cache-resident LC_DYLD_EXPORTS_TRIE in place,
# and also works on ordinary on-disk dylibs.
#
# Usage: dyld-info-exports [--help] [--filter=REGEX] [--arch=ARCH] <binary-path>
#
#   exports  [ {address, name} ]  — name includes the leading underscore
#   arch     string               — parsed from the dyld_info output header
#   total    integer
set -eu
cd "$(dirname "$0")"
# shellcheck source=../lib/common.sh
source "../lib/common.sh"

for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    cat <<EOF
dyld-info-exports — emit the export trie of a Mach-O image as JSON.

Usage:
  scripts/bin/dyld-info-exports [--filter=POSIX-REGEX] [--arch=ARCH] <path-to-macho>

Options:
  --filter=REGEX   only report exports whose name matches REGEX
  --arch=ARCH      request a slice (e.g. arm64e). NOTE: the arm64e dyld
                   shared cache holds only the arm64e slice, so the reported
                   arch is always parsed from the output header, never from
                   this flag.

Outputs scripts/bin/output-schema.json envelope with observations:
  exports  [ {address, name} ]
  arch     string
  total    integer

Examples:
  scripts/bin/dyld-info-exports /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation
  scripts/bin/dyld-info-exports --filter='^_CFRunLoop' /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation

Exit codes: 0 ok, 1 tool-failed, 2 invocation-error
EOF
    exit 0
  fi
done

parse_tool_args "$@"

if ! assert_binary_present "$BINARY"; then
  emit_tool_failed "dyld_info" "${BINARY:-}" "binary not found: ${BINARY:-<unspecified>}"
  exit 1
fi

if ! command -v dyld_info >/dev/null 2>&1; then
  emit_tool_missing "dyld_info" "$BINARY" "xcode-select --install (ships /usr/bin/dyld_info)"
  exit 0
fi

# Extract options.
filter=""
arch=""
for arg in "$@"; do
  if [[ "$arg" == --filter=* ]]; then filter="${arg#--filter=}"; fi
  if [[ "$arg" == --arch=* ]]; then arch="${arg#--arch=}"; fi
done

start_ms="$(_now_ms)"

dyld_args=(-exports)
if [[ -n "$arch" ]]; then dyld_args=(-arch "$arch" -exports); fi

if ! raw=$(dyld_info "${dyld_args[@]}" "$BINARY" 2>/dev/null); then
  emit_tool_failed "dyld_info" "$BINARY" "dyld_info ${dyld_args[*]} failed for $BINARY"
  exit 1
fi

# The arch is whatever dyld_info actually reported, not what we asked for.
# The arm64e shared cache holds only the arm64e slice.
reported_arch=$(printf '%s\n' "$raw" | sed -n 's/.*\[\([A-Za-z0-9_]*\)\]:$/\1/p' | head -1)
reported_arch="${reported_arch:-unknown}"

# Export lines: <spaces>0xADDR<spaces>_SYMBOL
exports_json=$(printf '%s\n' "$raw" | jq -Rn '
  [ inputs
    | (try (capture("^\\s+0x(?<address>[0-9A-Fa-f]+)\\s+(?<name>_\\S+)\\s*$")) catch null)
    | select(. != null)
    | {address: .address, name: .name}
  ]')

if [[ -n "$filter" ]]; then
  exports_json=$(printf '%s' "$exports_json" | jq --arg re "$filter" '[.[] | select(.name | test($re))]')
fi

total=$(printf '%s' "$exports_json" | jq 'length')

end_ms="$(_now_ms)"
duration=$(( end_ms - start_ms ))

jq -n \
  --arg binary "$BINARY" \
  --arg arch "$reported_arch" \
  --argjson exports "$exports_json" \
  --argjson total "$total" \
  --argjson duration "$duration" \
  '{tool: "dyld_info", binary: $binary, status: "ok", exit_code: 0, duration_ms: $duration,
    observations: {arch: $arch, exports: $exports, total: $total}}'
```

- [ ] **Step 2: Make it executable and check `--help`**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
chmod +x scripts/bin/dyld-info-exports
bash scripts/bin/dyld-info-exports --help
```
Expected: usage text on stdout, exit code 0.

- [ ] **Step 3: Verify against the cache-backed CoreFoundation**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
bash scripts/bin/dyld-info-exports \
  /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation \
  | jq '{status, arch: .observations.arch, total: .observations.total}'
```
Expected: `"ok"`, `"arm64e"`, and `total` of **3098**. If total is 0, the parse regex is wrong — check that export lines use two spaces and that the jq `capture` pattern is `^\\s+0x(...)\\s+(_\\S+)\\s*$`.

- [ ] **Step 4: Verify a filter works and a non-cache binary also works**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
bash scripts/bin/dyld-info-exports --filter='^_CFRunLoopGetCurrent$' \
  /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation \
  | jq '.observations.exports'
bash scripts/bin/dyld-info-exports /usr/lib/system/libsystem_pthread.dylib \
  | jq '{status, arch: .observations.arch, total: .observations.total}'
```
Expected: first returns exactly one export with name `_CFRunLoopGetCurrent`; second returns `"ok"` and a non-zero total.

- [ ] **Step 5: Verify the failure path**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
bash scripts/bin/dyld-info-exports /nonexistent/path | jq '{status, error}'
```
Expected: `"tool-failed"` and an `error` mentioning "binary not found".

- [ ] **Step 6: Commit**

```bash
cd /Users/vaithianathan/revOS-work/revOS
git add scripts/bin/dyld-info-exports
git diff --cached --name-only
git commit -m "feat(harness): add dyld-info-exports wrapper for cache-backed images

On macOS 27 the CoreFoundation and Foundation framework paths are dangling
symlinks; the real images live in the arm64e dyld shared cache. nm and otool
cannot open them ('No such file or directory'), which made three sprint-1
agents hand-roll the same dyld_info invocation.

This wrapper reads the export trie in place and works on ordinary on-disk
dylibs too. Verified: 3098 exports for the arm64e CoreFoundation slice,
matching the count independently recorded by the cf-types agent.

The reported arch is parsed from the dyld_info output header rather than the
--arch flag, because the arm64e cache holds only the arm64e slice."
# Do not push. The controller reviews this branch and merges it to `main`
# after the task review passes.
```

---

### Task 3: Detect cache-backed binaries and fall back automatically

**Files:**
- Modify: `scripts/lib/common.sh` (add `is_cache_backed`, `emit_cache_backed`; extend `assert_binary_present`)
- Modify: `scripts/bin/nm-symbols` (fallback path)
- Modify: `scripts/bin/otool-exports` (fallback path)
- Modify: `scripts/bin/output-schema.json` (add `cache-backed` to the `status` enum)

**Interfaces:**
- Consumes: `scripts/bin/dyld-info-exports` from Task 2 (invoked as a subprocess, not sourced).
- Produces:
  - `common.sh`: `is_cache_backed <path>` → returns 0 if the path is a dangling symlink that `dyld_info` can read, else 1. `assert_binary_present <path>` now sets `BIN_VALID` to `ok`, `cache-backed`, or `missing`. `emit_cache_backed <tool> <binary> <hint>` → JSON envelope with `status: "cache-backed"`. `emit_invocation_error <tool> <binary> <msg>` → JSON envelope with `status: "invocation-error"`, exit code 2.
  - `scripts/bin/dyld-info-exports`: its file-local `_emit_invocation_error` is replaced by `common.sh`'s `emit_invocation_error`, so the two emitters cannot drift. The Task 2 re-review flagged the duplication as a drift risk.

- [ ] **Step 1: Add `is_cache_backed` and `emit_cache_backed` to `common.sh`**

Insert before the `# ---- json emit helpers ----` block in `scripts/lib/common.sh`:

```bash
# ---- cache-backed image detection ---------------------------------------
# On macOS 27 the system frameworks are NOT Mach-O files on disk: the framework
# path is a dangling symlink (test -e is false, test -L is true) and the real
# image is resident in the arm64e dyld shared cache. `nm` and `otool` cannot
# open such a path, and report "No such file or directory" — which reads as
# "the library is gone" rather than "the library is not a file".
#
# is_cache_backed <path>  -> 0 if the path is a cache-backed stub, else 1.
is_cache_backed() {
  local binary="$1"
  # Must be a symlink that does not resolve: that is the stub shape.
  [[ -L "$binary" ]] || return 1
  # If it resolves, it is a real file and not a cache stub.
  [[ -e "$binary" ]] && return 1
  command -v dyld_info >/dev/null 2>&1 || return 1
  # dyld_info can read it out of the cache.
  dyld_info -exports "$binary" >/dev/null 2>&1
}
```

Insert after `emit_tool_failed` in `scripts/lib/common.sh`:

```bash
# Emit a cache-backed envelope. The image is not a file on disk; it lives in
# the dyld shared cache. $3 is a hint describing the way forward.
emit_cache_backed() {
  local tool="$1"
  local binary="$2"
  local hint="${3:-}"
  local start="$WRAPPER_START_MS"
  local now
  now="$(_now_ms)"
  local duration=0
  if [[ -n "${start:-}" ]]; then duration=$(( now - start )); fi
  jq -n \
    --arg tool "$tool" \
    --arg binary "$binary" \
    --arg hint "$hint" \
    --argjson duration "$duration" \
    '{tool: $tool, binary: $binary, status: "cache-backed", exit_code: 1, duration_ms: $duration,
      error: ("image is not a Mach-O file on disk; it is resident in the dyld shared cache"),
      hint: $hint}'
}
```

- [ ] **Step 2: Extend `assert_binary_present` to recognise cache-backed stubs**

Replace the body of `assert_binary_present` in `scripts/lib/common.sh` with:

```bash
# Detect whether the binary argument exists and is non-empty. Sets a global
# BIN_VALID=ok|cache-backed|missing for callers.
#
# "cache-backed" is the macOS 27 case: a dangling symlink whose real image
# lives in the dyld shared cache. It is NOT missing — treating it as missing
# is what made three sprint-1 agents report CoreFoundation as unavailable.
assert_binary_present() {
  local binary="$1"
  if [[ -z "$binary" ]]; then
    BIN_VALID="missing"
    return 1
  fi
  if [[ ! -e "$binary" ]]; then
    if is_cache_backed "$binary"; then
      BIN_VALID="cache-backed"
      return 0
    fi
    BIN_VALID="missing"
    return 1
  fi
  # shellcheck disable=SC2034  # consumed by the sourcing wrapper, not here
  BIN_VALID="ok"
  return 0
}
```

- [ ] **Step 3: Make `nm-symbols` fall back to `dyld_info` for cache-backed images**

In `scripts/bin/nm-symbols`, replace the block:
```bash
if ! assert_binary_present "$BINARY"; then
  emit_tool_failed "nm" "${BINARY:-}" "binary not found: ${BINARY:-<unspecified>}"
  exit 1
fi
```
with:
```bash
if ! assert_binary_present "$BINARY"; then
  emit_tool_failed "nm" "${BINARY:-}" "binary not found: ${BINARY:-<unspecified>}"
  exit 1
fi

# Cache-backed images (macOS 27 system frameworks) are not files on disk and
# nm cannot open them. Fall back to the export trie instead of reporting a
# misleading "binary not found".
if [[ "${BIN_VALID:-missing}" == "cache-backed" ]]; then
  # The sibling wrapper, relative to THIS wrapper's own directory. Every
  # wrapper does `cd "$(dirname "$0")"` at the top, so the cwd is already
  # scripts/bin and the path "scripts/bin/dyld-info-exports" does NOT resolve
  # (exit 127). Use the sibling form.
  fallback=$(bash ./dyld-info-exports ${filter:+--filter="$filter"} "$BINARY" 2>/dev/null || true)
  if [[ -n "$fallback" ]] && printf '%s' "$fallback" | jq -e '.status == "ok"' >/dev/null 2>&1; then
    # kind is null, not "T": the export trie (LC_DYLD_EXPORTS_TRIE) carries an
    # address and a name but NO symbol kind. nm distinguishes T/D/S/B/... and
    # this fallback cannot. Labelling every export "T" would be a false claim
    # about data symbols such as _dispatch_root_queues, and evidence records
    # quote this output verbatim.
    # `binary` is REQUIRED by scripts/bin/output-schema.json, so the fallback
    # envelope must carry it. The wrapper's own envelope has it; pass it through.
    # `arch` MUST be passed through. The brief's own Note requires it ("the
    # fallback must simply pass through whatever `arch` and `exports` the
    # wrapper reports"), and dyld-info-exports goes out of its way to compute
    # and justify reported_arch precisely because a mislabelled slice is silent
    # wrong data. An evidence record quoting this output must be able to state
    # which slice its symbols came from.
    # `exit_code` is hard-coded 0 because the guard above has already proven
    # .status == "ok"; relaying it could only ever contradict the status.
    printf '%s' "$fallback" | jq --arg source_tool "dyld_info" \
      '{tool: "nm", binary: .binary, source_tool: $source_tool, status: .status, exit_code: 0,
        duration_ms: .duration_ms,
        observations: {arch: .observations.arch,
                       symbols: [.observations.exports[] | {address, kind: null, name, section: null}],
                       total: .observations.total, kind_unknown: true}}'
    exit 0
  fi
  emit_cache_backed "nm" "$BINARY" "use scripts/bin/dyld-info-exports to read the export trie"
  exit 1
fi
```

Move the `filter` extraction **above** this block so the fallback can use it. The final order in the file must be: `parse_tool_args` → filter/arch extraction → `assert_binary_present` → cache-backed fallback → tool-presence check → `nm` invocation. Apply the same reordering to the existing filter-extraction block that currently sits after the `assert_binary_present` call — delete it from its old position and place it before.

- [ ] **Step 3b: Move the `invocation-error` emitter into `common.sh`**

Task 2's `dyld-info-exports` grew a file-local `_emit_invocation_error`. Task 3 is
the task that gives `common.sh` the full status vocabulary, so this is the moment
to put it in one place.

Add to `scripts/lib/common.sh`, next to the other emitters:

```bash
# Emit an invocation-error envelope. $3 is the failure message. Exit code 2,
# distinct from 1 (tool-failed) and 127 (tool-not-installed).
emit_invocation_error() {
  local tool="$1"
  local binary="$2"
  local msg="$3"
  local start="$WRAPPER_START_MS"
  local now
  now="$(_now_ms)"
  local duration=0
  if [[ -n "${start:-}" ]]; then duration=$(( now - start )); fi
  jq -n \
    --arg tool "$tool" \
    --arg binary "$binary" \
    --arg msg "$msg" \
    --argjson duration "$duration" \
    '{tool: $tool, binary: $binary, status: "invocation-error", exit_code: 2, duration_ms: $duration, error: $msg}'
}
```

Then replace `dyld-info-exports`'s file-local `_emit_invocation_error` with calls
to `emit_invocation_error`, and delete the local definition.

**Note for Task 3's implementer:** do NOT bake any assumption about which slice
the fallback reports. Task 5 changes `dyld-info-exports` to default to the
host-native slice; the fallback must simply pass through whatever `arch` and
`exports` the wrapper reports.

- [ ] **Step 4: Make `otool-exports` report cache-backed status instead of failing**

In `scripts/bin/otool-exports`, replace its `assert_binary_present` failure block with:
```bash
if ! assert_binary_present "$BINARY"; then
  emit_tool_failed "otool" "${BINARY:-}" "binary not found: ${BINARY:-<unspecified>}"
  exit 1
fi

# Cache-backed images (macOS 27 system frameworks) have no file to run
# `otool -L` against. Report the distinct status rather than a misleading
# "binary not found"; scripts/bin/dyld-info-exports still reads their exports.
if [[ "${BIN_VALID:-missing}" == "cache-backed" ]]; then
  emit_cache_backed "otool" "$BINARY" "use scripts/bin/dyld-info-exports to read the export trie"
  exit 1
fi
```

- [ ] **Step 4b: Add `cache-backed` to the wrapper-output status enum**

`scripts/bin/output-schema.json` constrains `status` to
`["ok", "tool-not-installed", "tool-failed", "invocation-error", "rea-cli's-subcommand-not-found"]`.
The new `emit_cache_backed` emits `status: "cache-backed"`, which is not in that
enum — the wrapper would violate the contract it claims to satisfy. Add it:

```json
    "status": {
      "type": "string",
      "enum": ["ok", "tool-not-installed", "tool-failed", "cache-backed", "invocation-error", "rea-cli's-subcommand-not-found"]
    },
```

- [ ] **Step 5: Verify the fallback works on CoreFoundation**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
bash scripts/bin/nm-symbols /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation \
  | jq '{status, source_tool, total: .observations.total}'
```
Expected: `"ok"`, `"dyld_info"`, and `total` of **3098**.

- [ ] **Step 6: Verify the normal path is unchanged**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
bash scripts/bin/nm-symbols /usr/lib/system/libsystem_pthread.dylib | jq '{status, total: .observations.total}'
bash scripts/bin/otool-exports /usr/lib/system/libsystem_pthread.dylib | jq '{status, libs: (.observations.linked | length)}'
```
Expected: both `"ok"`, with a non-zero symbol total and a non-zero linked-library count. Neither should report `source_tool`.

- [ ] **Step 7: Verify the missing-path path still fails correctly**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
bash scripts/bin/nm-symbols /nonexistent/path | jq '{status, error}'
```
Expected: `"tool-failed"`.

- [ ] **Step 8: Re-run shellcheck and the evidence validator**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
SHELL_FILES=$(grep -rlI '^#!/usr/bin/env bash' scripts/ | sort)
shellcheck --severity=warning --exclude=SC1091 $SHELL_FILES && echo "SHELLCHECK OK"
python3 scripts/lib/validate_evidence.py . | tail -1
```
Expected: `SHELLCHECK OK` and `validated 76 evidence records: 76 ok, 0 failing`.

- [ ] **Step 9: Commit**

```bash
cd /Users/vaithianathan/revOS-work/revOS
git add scripts/lib/common.sh scripts/bin/nm-symbols scripts/bin/otool-exports
git diff --cached --name-only
git commit -m "feat(harness): detect cache-backed images and fall back to dyld_info

The macOS 27 system frameworks are dangling symlinks into the arm64e dyld
shared cache. nm and otool cannot open them and reported 'binary not found',
which reads as 'the library is gone' and cost three sprint-1 agents a
detour each.

- is_cache_backed() identifies a dangling symlink that dyld_info can read.
- assert_binary_present() now reports ok | cache-backed | missing instead of
  collapsing cache-backed into missing.
- nm-symbols falls back to the export trie for cache-backed images and
  reports source_tool=dyld_info so the provenance is explicit.
- otool-exports emits a distinct status=cache-backed with a pointer to
  dyld-info-exports.

Verified: nm-symbols on CoreFoundation now returns 3098 symbols with
source_tool=dyld_info; the on-disk path is unchanged."
# Do not push. The controller reviews this branch and merges it to `main`
# after the task review passes.
```

---

### Task 4: Add `dyld_info` to the evidence schema and add `capability-probe`

**Files:**
- Modify: `evidence/schema.json` (`observation.tool` enum)
- Modify: `scripts/bin/output-schema.json` (`tool` enum)
- Create: `scripts/bin/capability-probe`

**Interfaces:**
- Consumes: `parse_tool_args`, `emit_ok`, `emit_tool_missing`, `emit_tool_failed` from `common.sh`.
- Produces: `scripts/bin/capability-probe [--symbols=FILE] [--arch=ARCH] <binary-path>` emitting `observations.symbols` (array of `{name, status}` where status ∈ `works | traps | missing | private`), `observations.total`, `observations.summary` (object counting each status).

- [ ] **Step 1: Extend the schema's `tool` enum**

In `evidence/schema.json`, find:
```json
        "tool": {
          "enum": ["otool", "nm", "strings", "class-dump", "dsymutil", "dtrace", "rea", "other"]
        },
```
and replace it with:
```json
        "tool": {
          "enum": ["otool", "nm", "strings", "class-dump", "dsymutil", "dtrace", "dyld_info", "rea", "other"]
        },
```

- [ ] **Step 1b: Add `dyld_info` to the wrapper-output schema's tool enum**

There are TWO schemas, and the plan originally named only one.
`evidence/schema.json` constrains evidence records. `scripts/bin/output-schema.json`
constrains the envelope every wrapper under `scripts/bin/` emits, and its `tool`
enum is `["otool", "nm", "strings", "class-dump", "rea"]` — with no `dyld_info`.
Task 2's `dyld-info-exports` already emits `tool: "dyld_info"`, so it violates
the wrapper contract it documents. Fix it here too:

```json
    "tool": {
      "type": "string",
      "enum": ["otool", "nm", "strings", "class-dump", "dyld_info", "rea"]
    },
```

- [ ] **Step 2: Prove the schema now accepts `dyld_info` and still rejects junk**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
cat > /tmp/probe-dyld-info.json <<'EOF'
{
  "subsystem": "cf-types",
  "subject": "CFRunLoopGetCurrent",
  "subject_kind": "function",
  "source_artifact": {
    "path": "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "format": "framework"
  },
  "observation": {
    "tool": "dyld_info",
    "tool_invocation": "dyld_info -arch arm64e -exports /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
    "summary": "probe record for schema acceptance"
  },
  "claim": "schema acceptance probe",
  "claim_status": "observed",
  "cross_reference": [],
  "confidence": 0.9,
  "reproducer": "dyld_info -arch arm64e -exports /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
}
EOF
mkdir -p /tmp/ledger-probe && cp /tmp/probe-dyld-info.json /tmp/ledger-probe/
python3 - <<'EOF'
import json, subprocess, pathlib, shutil
root = pathlib.Path("/tmp/ledger-probe")
shutil.copy("evidence/schema.json", root / "schema.json")
print(subprocess.run(["python3", "scripts/lib/validate_evidence.py", str(root)], capture_output=True, text=True).stdout)
EOF
```
Expected: `validated 1 evidence records: 1 ok, 0 failing`.

Then prove a bogus tool is still rejected:
```bash
cd /Users/vaithianathan/revOS-work/revOS
python3 - <<'EOF'
import json, pathlib
p = pathlib.Path("/tmp/ledger-probe/probe-dyld-info.json")
d = json.loads(p.read_text())
d["observation"]["tool"] = "not_a_real_tool"
p.write_text(json.dumps(d))
EOF
python3 - <<'EOF'
import subprocess
r = subprocess.run(["python3", "scripts/lib/validate_evidence.py", "/tmp/ledger-probe"], capture_output=True, text=True)
print("exit:", r.returncode)
print(r.stdout)
EOF
```
Expected: a non-zero exit and a message naming the bad enum value.

- [ ] **Step 3: Write the `capability-probe` wrapper**

Create `scripts/bin/capability-probe` with content:

```bash
#!/usr/bin/env bash
# scripts/bin/capability-probe
#
# Classify each exported symbol of a Mach-O image into a capability status:
#
#   works   — the symbol resolves and the probe call returned normally
#   traps   — the symbol resolves but the probe call aborted the process
#   missing — the symbol is not in the export trie
#   private — the symbol exists only under an Apple-private (double-underscore)
#             name and has no public spelling
#
# This is the primitive behind the capability matrix: it distinguishes the
# gap classes that sprint 1 had no vocabulary for. "present but traps" is a
# different problem from "absent", and "absent publicly but present
# privately" is a third.
#
# Usage: capability-probe [--help] [--symbols=FILE] [--arch=ARCH] <binary-path>
#
# The probe itself is a dlsym/link-time check plus an optional call gate; the
# default mode is a static classification that never executes target code.
set -eu
cd "$(dirname "$0")"
# shellcheck source=../lib/common.sh
source "../lib/common.sh"

for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    cat <<EOF
capability-probe — classify exported symbols into works / traps / missing / private.

Usage:
  scripts/bin/capability-probe [--symbols=FILE] [--arch=ARCH] <path-to-macho>

Options:
  --symbols=FILE   a text file of symbol names, one per line. When omitted,
                   the symbol list is taken from the image's export trie.
  --arch=ARCH      request a slice (e.g. arm64e)

Outputs scripts/bin/output-schema.json envelope with observations:
  symbols  [ {name, status} ]   status in works|traps|missing|private
  total    integer
  summary  { works, traps, missing, private }

Notes:
  Default mode is STATIC: it classifies names, it does not execute target
  code. A symbol is 'works' when it has a public spelling in the export
  trie, 'private' when it exists only with a double-underscore Apple-private
  name, and 'missing' when the requested name is absent. 'traps' is only
  assigned by the --call mode, which is intentionally not implemented here;
  runtime trapping is measured by the Phase 0c probe harness.

Exit codes: 0 ok, 1 tool-failed, 2 invocation-error
EOF
    exit 0
  fi
done

parse_tool_args "$@"

if ! assert_binary_present "$BINARY"; then
  emit_tool_failed "dyld_info" "${BINARY:-}" "binary not found: ${BINARY:-<unspecified>}"
  exit 1
fi

if ! command -v dyld_info >/dev/null 2>&1; then
  emit_tool_missing "dyld_info" "$BINARY" "xcode-select --install (ships /usr/bin/dyld_info)"
  exit 0
fi

symbols_file=""
arch=""
for arg in "$@"; do
  if [[ "$arg" == --symbols=* ]]; then symbols_file="${arg#--symbols=}"; fi
  if [[ "$arg" == --arch=* ]]; then arch="${arg#--arch=}"; fi
done

start_ms="$(_now_ms)"

dyld_args=(-exports)
if [[ -n "$arch" ]]; then dyld_args=(-arch "$arch" -exports); fi
if ! raw=$(dyld_info "${dyld_args[@]}" "$BINARY" 2>/dev/null); then
  emit_tool_failed "dyld_info" "$BINARY" "dyld_info ${dyld_args[*]} failed for $BINARY"
  exit 1
fi

# Public names: exactly one leading underscore.
public_json=$(printf '%s\n' "$raw" | jq -Rn '
  [ inputs
    | (try (capture("^\\s+0x(?<address>[0-9A-Fa-f]+)\\s+(?<name>_\\S+)\\s*$")) catch null)
    | select(. != null)
    | {address: .address, name: .name}
  ]')

public_names=$(printf '%s' "$public_json" | jq -r '.[] | select(.name | startswith("__") | not) | .name')
private_names=$(printf '%s' "$public_json" | jq -r '.[] | select(.name | startswith("__")) | .name')

if [[ -n "$symbols_file" ]]; then
  if [[ ! -f "$symbols_file" ]]; then
    emit_tool_failed "capability_probe" "$BINARY" "symbols file not found: $symbols_file"
    exit 1
  fi
  requested=$(grep -vE '^[[:space:]]*(#|$)' "$symbols_file" || true)
else
  requested=""
fi

if [[ -n "$requested" ]]; then
  symbols_json=$(printf '%s\n' "$requested" | while IFS= read -r sym; do
    [[ -z "$sym" ]] && continue
    if printf '%s\n' "$public_names" | grep -qxF "$sym"; then
      printf '{"name":%s,"status":"works"}\n' "$(printf '%s' "$sym" | jq -R .)"
    elif printf '%s\n' "$private_names" | grep -qxF "$sym"; then
      printf '{"name":%s,"status":"private"}\n' "$(printf '%s' "$sym" | jq -R .)"
    else
      printf '{"name":%s,"status":"missing"}\n' "$(printf '%s' "$sym" | jq -R .)"
    fi  done | jq -Rn '[inputs | fromjson]')
else
  symbols_json=$(printf '%s' "$public_json" | jq 'map({name, status: (if (.name | startswith("__")) then "private" else "works" end)})')
fi

total=$(printf '%s' "$symbols_json" | jq 'length')
summary=$(printf '%s' "$symbols_json" | jq '{works: (map(select(.status=="works")) | length),
  traps: (map(select(.status=="traps")) | length),
  missing: (map(select(.status=="missing")) | length),
  private: (map(select(.status=="private")) | length)}')

end_ms="$(_now_ms)"
duration=$(( end_ms - start_ms ))

jq -n \
  --arg binary "$BINARY" \
  --argjson symbols "$symbols_json" \
  --argjson total "$total" \
  --argjson summary "$summary" \
  --argjson duration "$duration" \
  '{tool: "dyld_info", binary: $binary, status: "ok", exit_code: 0, duration_ms: $duration,
    observations: {symbols: $symbols, total: $total, summary: $summary}}'
```

- [ ] **Step 4: Make it executable and check `--help`**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
chmod +x scripts/bin/capability-probe
bash scripts/bin/capability-probe --help
```
Expected: usage text, exit code 0.

- [ ] **Step 5: Verify classification on a real image**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
bash scripts/bin/capability-probe \
  /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation \
  | jq '{status, total: .observations.total, summary: .observations.summary}'
```
Expected: `"ok"`, `total` of **3098**, and a summary where `works + private == 3098`
and `traps == 0` and `missing == 0`. Measured on this host: `works: 2078`,
`private: 1020`. The 1020 `__`-prefixed names are the Apple-private surface —
the largest single category, and the one sprint 1 had no way to express.

- [ ] **Step 6: Verify the explicit symbol list path distinguishes all three static states**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
cat > /tmp/probe-syms.txt <<'EOF'
_CFRunLoopGetCurrent
_CFGetRetainCount
_CFRetainCount
__CFStringCreateTaggedPointerString
_CFThisSymbolDoesNotExist
EOF
bash scripts/bin/capability-probe --symbols=/tmp/probe-syms.txt \
  /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation \
  | jq -r '.observations.symbols[] | "  \(.name) -> \(.status)"'
```
Expected, exactly:
```
  _CFRunLoopGetCurrent -> works
  _CFGetRetainCount -> works
  _CFRetainCount -> missing
  __CFStringCreateTaggedPointerString -> private
  _CFThisSymbolDoesNotExist -> missing
```

Two of those five expectations are cross-validations of sprint-1 findings:
`_CFGetRetainCount` is `works` while `_CFRetainCount` is `missing`, which is
exactly the correction the `cf-types` agent recorded — the public symbol is
`CFGetRetainCount`, not `CFRetainCount`. And `__CFStringCreateTaggedPointerString`
is present in the arm64e export trie at offset `0x0016E624`, the same address
the `cf-types` agent independently recorded.

If `__CFStringCreateTaggedPointerString` comes back as `works` instead of
`private`, the `public_names` filter is wrong — it must exclude `__`-prefixed
names, and the `private` branch is unreachable otherwise.

- [ ] **Step 7: Re-run shellcheck and the evidence validator**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
SHELL_FILES=$(grep -rlI '^#!/usr/bin/env bash' scripts/ | sort)
shellcheck --severity=warning --exclude=SC1091 $SHELL_FILES && echo "SHELLCHECK OK"
python3 scripts/lib/validate_evidence.py . | tail -1
```
Expected: `SHELLCHECK OK` and `validated 76 evidence records: 76 ok, 0 failing`.

- [ ] **Step 8: Commit**

```bash
cd /Users/vaithianathan/revOS-work/revOS
git add evidence/schema.json scripts/bin/capability-probe
git diff --cached --name-only
git commit -m "feat(harness): add dyld_info to the evidence tool enum and add capability-probe

- The schema's observation.tool enum lacked dyld_info, so three sprint-1
  agents had to record their cache-backed export observations as 'other',
  losing the tool identity. dyld_info is now a first-class enum member.
- capability-probe classifies every exported symbol into
  works|traps|missing|private, which is the vocabulary sprint 1 lacked:
  'present but traps' (getCFRunLoop on Linux) is a different problem from
  'absent', and 'publicly absent but privately present' is a third.
  Default mode is static and never executes target code."
# Do not push. The controller reviews this branch and merges it to `main`
# after the task review passes.
```

---

### Task 5: Host-native default slice, and a corpus consistency audit (slice attribution + tooling-state staleness)

**Files:**
- Modify: `scripts/bin/dyld-info-exports` (default slice selection)
- Modify: `scripts/bin/capability-probe` (delegate its export extraction to `dyld-info-exports` instead of re-parsing the export trie; adopt the same `--arch` invocation-error guard)
- Create: `scripts/lib/audit_slice_attribution.py`
- Modify: `subsystems/libdispatch/evidence/*.json` (correction of wrong-slice addresses — the `libdispatch` subsystem owns these files; this task is an explicitly granted ownership exception, recorded in the ledger)

**Status note (2026-10-22).** Steps 1, 2, 2c, 5c and 5d — the wrapper-side
changes — are **already implemented and committed** at `c252fee`. The implementer
hit the provider's 300s first-event timeout while surveying the corpus, and the
uncommitted wrapper work was preserved as that commit. A later task continues
from here and must not redo them.

**Interfaces:**
- Consumes: `scripts/bin/dyld-info-exports` from Task 2 (whose fix round 1 bounded the export parse to a single slice); the 12 libdispatch evidence records.
- Produces: `python3 scripts/lib/audit_slice_attribution.py [ROOT_DIR]` → exit 0 when every cited address is attributable to the slice its record claims, exit 1 with one line per violation. `scripts/bin/dyld-info-exports` with no `--arch` now selects the **host-native** slice.

**Background — why this task exists.** Task 2's review found that `dyld_info -exports` on a fat dylib emits one section per slice, and that the original wrapper merged them under the first slice's arch label. Fixing that exposed a **pre-existing defect in the shipped evidence corpus**, which this task corrects.

**There are TWO corpus defects, and they are different species.** Do not conflate them.

| | Defect 1 — slice attribution | Defect 2 — tooling-state staleness |
|---|---|---|
| What is wrong | the quoted **address** belongs to the wrong slice | a surrounding **sentence** describes superseded tooling behaviour |
| Severity | data corruption — the datum itself is false | narrative only — the datum and its reproducer are still correct |
| Scope | 11 of 12 `libdispatch` records | 26 `cf-runtime` records |
| Fix | re-derive the address from the correct slice | update the sentence to describe current behaviour; **leave the quoted output and the reproducer alone** |

Defect 2 in full: every `cf-runtime` record's `observation.summary` opens with
"CoreFoundation ships no standalone Mach-O on macOS 27 … `nm-symbols` and
`otool-exports` both return `status=tool-failed` against this path". That was
true when observed. **After Task 3 it is false** — `nm-symbols` now returns
`status: "ok"` with `source_tool: "dyld_info"` and 3098 exports, and
`otool-exports` reports `status: "cache-backed"`.

**Defect 2 does NOT invalidate any claim.** The quoted excerpt
(`0x0006A120  _CFRunLoopAddObserver`) is still correct, and the record's
`reproducer` — `dyld_info -exports … | grep -w '_CFRunLoopAddObserver'` — still
reproduces it byte-for-byte, because `dyld_info` was always the tool that
produced it. Only the prose describing what the *wrappers* did is stale. The
correct fix is to update the prose and change nothing else; the wrong fix is to
re-derive the whole observation and overwrite a still-correct datum.

Measured on this host:

```
nm -arch arm64e -gU libdispatch.dylib | grep ' T _dispatch_async$'
  000000000000a100 T _dispatch_async          <- arm64e
nm -arch x86_64 -gU libdispatch.dylib | grep ' T _dispatch_async$'
  0000000000008827 T _dispatch_async          <- x86_64
```

`libdispatch.dylib` is a fat binary with slices `x86_64 arm64e`. **11 of the 12 libdispatch evidence records cite x86_64 addresses while their `observation.tool_invocation` says `nm -arch arm64e -gU`.** Only `dispatch_queue_create` (address `0xc2c4`) is correct. The likely cause: `nm -gU` with no `-arch` dumps **all** slices with x86_64 first, and the quoted output came from that run while the recorded invocation named the arm64e run.

This is a **provenance defect**, not merely a wrong number. The repo's honesty contract requires `observation.tool_invocation` to be the command that produced the quoted output. The symbol identities, presence/absence claims, and counts in those records remain correct — the API surface of libdispatch is identical across slices. Only the addresses and the stated invocation are wrong.

**Address space note.** `nm` reports *symbol table* addresses; `dyld_info -exports` reports *export trie* addresses. They are different address spaces and are usually but not always equal. The audit tool must therefore build its per-slice tables with the SAME tool family the record claims, and never compare an `nm` address against an export-trie table.

- [ ] **Step 1: Change the default slice selection to host-native**

Currently the wrapper selects the **first** section in fat-header order, which is `x86_64` on this host — even though the host is arm64 and the entire evidence corpus was built from the arm64e slice. `nm` with no `-arch` dumps every slice, so there is no "nm default" to match; the useful default is the slice **this machine actually runs**.

Required behaviour:
- `--arch=ARCH` selects the slice named `ARCH`.
- No `--arch` → select the **host-native** slice. On an arm64 host that is `arm64e` when the image has it, else `arm64`; on an x86_64 host, `x86_64`. If the image has only one slice, that one is used regardless.
- `observations.arch` and `observations.exports` must always describe the same slice.
- A cache-backed image has exactly one slice and must still yield `arm64e` / **3098** for CoreFoundation.

Implement by parsing **all** section headers from the `dyld_info -exports` output, grouping the export lines under their owning header, then selecting the group. Prefer not to re-invoke `dyld_info` a second time.

- [ ] **Step 2: Verify the new default selection**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS/.worktrees/phase-0a
bash scripts/bin/dyld-info-exports /usr/lib/system/introspection/libdispatch.dylib | jq -c '{arch: .observations.arch, total: .observations.total}'
bash scripts/bin/dyld-info-exports /usr/lib/system/libsystem_kernel.dylib | jq -c '{arch: .observations.arch, total: .observations.total}'
bash scripts/bin/dyld-info-exports /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation | jq -c '{arch: .observations.arch, total: .observations.total}'
```
Expected on this arm64 host: `arm64e` for all three, with totals 419 (libdispatch arm64e), 1614 (libsystem_kernel arm64e), and **3098** (CoreFoundation).

Also confirm the explicit form still wins:
```bash
bash scripts/bin/dyld-info-exports --arch=x86_64 /usr/lib/system/libsystem_kernel.dylib | jq -c '{arch: .observations.arch, total: .observations.total}'
```
Expected: `x86_64`, 1611.

- [ ] **Step 2c: Make `capability-probe` delegate to `dyld-info-exports`**

`capability-probe` currently re-implements the export-trie parse. That is a
**second copy of the same logic**, and it has already caused harm: Task 4's
brief carried the same multi-slice double-counting bug that Task 2's review had
just caught in `dyld-info-exports` (`/bin/ls` → total 2, distinct 1). A second
copy of a parser is a second place for the slice logic to drift, and the
host-native default this task introduces would have to be implemented twice.

So: **`capability-probe` must not parse the export trie itself.** It should
invoke the sibling wrapper — the same way `nm-symbols` does — and use the
`observations.exports` array it returns:

```bash
# The sibling wrapper, relative to THIS wrapper's own directory. Every wrapper
# does `cd "$(dirname "$0")"` at the top, so the cwd is already scripts/bin.
exports=$(bash ./dyld-info-exports ${arch:+--arch="$arch"} ${filter:+--filter="$filter"} "$BINARY" 2>/dev/null || true)
if [[ -z "$exports" ]] || ! printf '%s' "$exports" | jq -e '.status == "ok"' >/dev/null 2>&1; then
  emit_tool_failed "dyld_info" "$BINARY" "dyld_info -exports failed for $BINARY"
  exit 1
fi
```

Then classify using the returned `observations.exports` and `observations.arch`.
The `arch` the child reports is the slice the exports came from, so the
`works`/`private` split and the arch label are consistent by construction.

Also add the space-separated-flag guard that `dyld-info-exports` already has:
`--arch arm64e <path>` (space form) must produce `status: "invocation-error"`
with exit code 2, not a confusing `tool-failed` about a path named `arm64e`.
The implementer documented this as an accepted limitation in Task 4; closing it
here keeps the two wrappers consistent.

**Three Minor residuals from the Task 4 re-review, closed here because this is
the task that owns the file.**

1. **`--symbols=` with an empty flag VALUE still returns the entire trie.**
   `${arg#--symbols=}` yields `""` for `--symbols=`, which is indistinguishable
   from "flag absent", so the wrapper answers 3098 unrequested verdicts. This is
   the same symptom as the Task 4 Important 2, reached by a different trigger
   (an empty *value* rather than an empty *file*). Close it with a
   flag-presence flag — e.g. set `symbols_flag_set=1` when the argument is
   present, and test that instead of `-n "$symbols_file"`.
2. **The `--help` Notes still reference a `--call` mode that does not exist**,
   while the file's own header comment correctly says the wrapper "never
   assigns" `traps`. Remove the dangling reference.
3. **The `--help` exit-code line omits the `tool-not-installed` branch** (shell
   exit 0, envelope `exit_code: 127`), which the sibling documents. The line is
   not false, only incomplete. Add it.

- [ ] **Step 3: Write the slice-attribution audit tool**

Create `scripts/lib/audit_slice_attribution.py`. It must:

1. Walk every `subsystems/*/evidence/*.json`.
2. For each record, read `source_artifact.path` and `observation.tool_invocation`.
3. From the invocation, determine the **tool family** (`nm` or `dyld_info`) and the **claimed arch** (the `-arch` argument, or `UNSPECIFIED`).
4. Build per-slice symbol→address tables for the artifact using **that tool family** — `nm -arch <slice> -gU` or `dyld_info -arch <slice> -exports`. Cache per (artifact, tool family) so the audit is not quadratic. Note that some Apple-private symbols are absent from `nm` and present only in the export trie, and vice versa; build **both** tables and look the symbol up in either.
5. Extract every `(address, symbol)` pair the record quotes, from `observation.raw_output_excerpt`, `observation.summary`, and `claim`. Accept both the `nm` form (`000000000000a100 T _sym`) and the `dyld_info` form (`0x0000A100  _sym`).
6. For each pair, determine which slices place that symbol at that address. A pair is **CORRECT** when the claimed arch is among them. A pair is **MISMATCH** when it is not — that is the defect: the record quotes an address from a slice it does not claim.
7. Print one line per violation as `MISMATCH <file> <symbol> <address> claimed=<arch> actual=<slices>` and exit 1 if any exist, else print the count and exit 0.

8. Additionally, flag any record whose `observation.summary` asserts a wrapper
   status that the current harness no longer produces — specifically a summary
   claiming `tool-failed` for `nm-symbols` or `otool-exports` against a
   cache-backed path. Report these as `STALE-NARRATIVE <file>` and exit 1.
   This is a separate check from the address attribution, and it is a text
   check, not a symbol check.

9. **A reproducibility replay check — the third check, and the one that catches
   counts that were never right.**

   A third defect species was found while this task was in progress. The
   `foundation-bridge` record `foundation-shim-c-symbols-nm-cf8c8657.json`
   claims the BridgeSupport shim exports **46** `_NS*` symbols and **126**
   symbols in total. Measured twice — once through the wrapper, once through
   raw `nm -gU` — the real figures are **118** and **122**. The shim's mtime is
   2025-07-17, so it has not changed since the record was written: **the record
   was simply wrong when written**, at `confidence: 0.95` and
   `claim_status: observed`. Neither the slice-attribution check nor the
   stale-narrative check would have caught it.

   The check: **re-run the record's observation and compare it to the record's
   quoted output.** For each record, take the `observation.tool_invocation`
   and see whether the record's `raw_output_excerpt` still appears in what the
   tool produces now. If it does not, the record is not reproducible and is
   flagged as `MISMATCH-REPRO <file>`.

   **Security constraint — this must NOT execute arbitrary shell.** The
   `reproducer` and `tool_invocation` fields are data, and running them
   verbatim would be a command-injection footgun. Replay only invocations
   matching a **whitelisted set of shapes**, and skip anything else:

   - `nm -arch <arch> -gU <path>` (optionally followed by a `| grep <pattern>`)
   - `dyld_info [-arch <arch>] -exports <path>` (optionally followed by
     `| grep <pattern>`)
   - `scripts/bin/<one of the known wrappers> [flags] <path>` (optionally
     followed by `| grep <pattern>` or `| jq …`)

   Anything else is reported as `SKIPPED-REPRO <file>` (informational, not a
   failure) and left alone. Only the whitelisted forms are ever executed.

The tool must not modify anything. It is a detector; the correction is a separate, explicit step.

- [ ] **Step 4: Run the audit and confirm it detects the known defect**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS/.worktrees/phase-0a
python3 scripts/lib/audit_slice_attribution.py .
```
Expected: exit 1 with a `MISMATCH` line for each affected libdispatch record. If it reports zero, the tool is not detecting the defect it was written for — fix the tool before going on.

- [ ] **Step 5: Correct the affected libdispatch records**

For **each** record the audit flags:

1. Re-derive the correct arm64e observation with the tool the record actually uses:
   ```bash
   nm -arch arm64e -gU /usr/lib/system/introspection/libdispatch.dylib | grep -E ' T _dispatch_async$'
   ```
2. Update `observation.raw_output_excerpt` to the **arm64e** output line.
3. Update `observation.summary` so it states the arm64e address and slice, not the x86_64 one.
4. Update `observation.tool_invocation` if the quoted output was not produced by the recorded command — after this task it will have been, so the recorded invocation becomes true.
5. Update `claim` if it quotes a specific offset.
6. Leave `claim_status` and `confidence` unchanged **unless** re-derivation shows the underlying claim is wrong, in which case lower `confidence` and record why in `summary`.
7. Leave `subsystem`, `subject`, `subject_kind`, `cross_reference`, `reproducer` alone unless they also carry a wrong slice.

`dispatch_source_type_data_add` needs special care: its symbol is Apple-private and absent from `nm`, so the audit tool may not flag it. Verify it by hand:
```bash
dyld_info -arch arm64e -exports /usr/lib/system/introspection/libdispatch.dylib | grep -E '__dispatch_source_type_data_add$'
dyld_info -arch x86_64  -exports /usr/lib/system/introspection/libdispatch.dylib | grep -E '__dispatch_source_type_data_add$'
```
The record currently quotes the x86_64 address (`0x00068240`). Correct it to the arm64e address and fix the accompanying count reasoning — the record's current text divides a merged 38 by two arches to obtain 19; after correction it should derive 19 from a single arm64e section.

- [ ] **Step 5b: Correct the tooling-state-stale narratives**

For each of the 26 `cf-runtime` records and the 1 `foundation-bridge` record
whose `observation.summary` describes the pre-Task-3 wrapper behaviour:

1. **Do not change `observation.raw_output_excerpt`.** The quoted output is
   still exactly what the recorded `tool_invocation` produces.
2. **Do not change `observation.tool_invocation`.** It is still the command
   that produced the quoted output.
3. **Do not change `reproducer`.** It still reproduces the claim.
4. **Do change the stale sentence in `observation.summary`** so it describes
   current behaviour. The sentence that must go reads (in substance):
   "`nm-symbols` and `otool-exports` both return `status=tool-failed` against
   this path". Replace it with a statement of what the harness does now:
   the framework path is a dangling symlink into the arm64e dyld shared cache;
   since Phase 0a the harness reads it directly — `nm-symbols` returns
   `status: "ok"` with `source_tool: "dyld_info"` and 3098 exports, and
   `otool-exports` reports `status: "cache-backed"`.
5. Leave `claim`, `claim_status`, `confidence`, `subject`, `cross_reference`,
   and `source_artifact` untouched. The claim is unaffected.

Verify one record end to end after editing: the `reproducer` must still produce
the quoted line, and the summary must no longer claim `tool-failed`.

- [ ] **Step 5a: Correct the `foundation-bridge` record's wrong counts**

This is a different species from both Defect 1 and Defect 2: the record's
numbers were never right, and the tooling did not change.

`subsystems/foundation-bridge/evidence/foundation-shim-c-symbols-nm-cf8c8657.json`
claims the BridgeSupport shim exports **46** `_NS*` symbols and **126** symbols
in the dylib total. Measured twice — through the wrapper and through raw
`nm -gU` — the real figures are **118** and **122**. The shim's mtime is
2025-07-17, so it has not changed since the record was written.

The shim's 122 symbols are exactly 118 `_NS*` plus 4 `_CFBridging*`, with none
others. Verify that before editing:

```bash
SHIM=/System/Library/Frameworks/Foundation.framework/Versions/C/Resources/BridgeSupport/Foundation.dylib
nm -gU "$SHIM" | grep -cE '^[0-9a-fA-F]+ [A-Za-z] _NS'
nm -gU "$SHIM" | grep -cE '^[0-9a-fA-F]+ [A-Za-z] '
nm -gU "$SHIM" | grep -cE '^[0-9a-fA-F]+ [A-Za-z] _CFBridging'
```

Then, in that record only:
- Correct the two counts in `observation.summary`.
- Correct the `claim` if it states the counts.
- **Do not change** `claim_status` (still `observed`) and **do not lower
  `confidence`** — the underlying claim (that the shim re-exports the
  `_CFBridgingRetain`/`_CFBridgingRelease` toll-free helpers and the
  `_NS*` family, and that the real ObjC implementations live in the shared
  cache) is TRUE and was verified. Only the numbers attached to it were wrong.
- Correct `reproducer` if it names a figure the command does not produce.

- [ ] **Step 5c: Guard the cache-backed fallback against a malformed child payload**

`nm-symbols`'s cache-backed success branch runs `jq` over the child envelope and
reads `.observations.exports[]`. If a child ever returned `status: "ok"` without
`observations.exports`, that `jq` would fail and, under `set -e`/`pipefail`, the
wrapper would die with **zero bytes** — the exact failure mode this whole phase
exists to eliminate. It is unreachable with the in-repo child, which always
emits `observations.exports`, but it costs one condition to close.

Add the child-shape guard alongside the existing `.status == "ok"` guard, so the
fallback only proceeds when the child's payload actually carries exports.

- [ ] **Step 5d: Document the filter-dialect split in the two wrappers**

The on-disk path validates `--filter` with **awk** (POSIX ERE); the cache-backed
path delegates to `dyld-info-exports`, which validates with **jq** (Oniguruma).
The same argument can therefore succeed on one path and fail on the other:
`--filter='a{2'` is `tool-failed` on-disk and `ok` cache-backed. The on-disk
behaviour is the documented one, and it replaces what used to be a zero-byte
crash, so this is an improvement — but a caller should be told. Add one line to
each wrapper's `--help` stating which dialect that path accepts.

- [ ] **Step 6: Re-run the audit until it is clean**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS/.worktrees/phase-0a
python3 scripts/lib/audit_slice_attribution.py .
```
Expected: exit 0, zero `MISMATCH` lines, and a stated count of records checked.

Then confirm the evidence corpus still validates:
```bash
python3 scripts/lib/validate_evidence.py . | tail -1
```
Expected: `validated 76 evidence records: 76 ok, 0 failing`.

- [ ] **Step 7: Confirm the correction is real, not cosmetic**

Spot-check at least three corrected records against a fresh arm64e run:
```bash
cd /Users/vaithianathan/revOS-work/revOS/.worktrees/phase-0a
for s in _dispatch_async _dispatch_main _dispatch_group_create; do
  printf "  %-26s " "$s"
  nm -arch arm64e -gU /usr/lib/system/introspection/libdispatch.dylib | awk -v s="$s" '$3==s{print $1}'
done
```
Each printed address must equal the address quoted in the corresponding corrected record.

- [ ] **Step 8: Commit**

```bash
cd /Users/vaithianathan/revOS-work/revOS/.worktrees/phase-0a
git add scripts/bin/dyld-info-exports scripts/lib/audit_slice_attribution.py subsystems/libdispatch/evidence/
git diff --cached --name-only
git commit -m "fix(corpus): correct wrong-slice addresses in libdispatch evidence

Task 2's review found that dyld_info -exports emits one section per slice and
that the original wrapper merged them under the first slice's arch label.
Fixing that exposed a pre-existing defect in the shipped corpus.

libdispatch.dylib is a fat binary with slices x86_64 and arm64e. 11 of its 12
evidence records quote x86_64 addresses while their observation.tool_invocation
says 'nm -arch arm64e -gU'. Only dispatch_queue_create is correct. The quoted
output came from an nm run without -arch, which dumps every slice with x86_64
first.

This is a provenance defect as much as a wrong number: the honesty contract
requires tool_invocation to be the command that produced the quoted output. The
symbol identities, presence/absence claims and API-surface counts are all
unaffected — libdispatch exports the same surface on both slices.

- dyld-info-exports now defaults to the host-native slice instead of the first
  fat-header slice, so a default invocation on this arm64 host reports arm64e
  rather than x86_64.
- New scripts/lib/audit_slice_attribution.py attributes every cited address in
  the corpus to a slice and compares it against the slice each record claims.
  It is a detector, so this class of defect cannot recur silently.
- The affected libdispatch records are corrected to their arm64e addresses.

No claim changes status: every affected record was already claim_status
observed, and the observation is re-derived rather than assumed."
```

### Task 6: Add the gap-ledger schema and validator

**Files:**
- Create: `gap-ledger/schema.json`
- Create: `scripts/lib/validate_gap_ledger.py`
- Create: `gap-ledger/gaps/.gitkeep`

**Interfaces:**
- Consumes: `evidence/schema.json` (for cross-referencing) — the validator reads the schema, it does not import the module.
- Produces: `python3 scripts/lib/validate_gap_ledger.py [ROOT_DIR]` → exit 0 when every gap file conforms; exit 1 with one line per violation. Also writes `gap-ledger/index.json` when `--write-index` is passed.

**Background:** the gap ledger is the bridge between the evidence world and the code world. Its five invariants are the spec's §5.2. The most important is the last: **a gap whose `reverification.status` is `closed-upstream` must have `status: "dropped"`** — we do not implement gaps that no longer exist.

- [ ] **Step 1: Write the gap-ledger schema**

Create `gap-ledger/schema.json` with content:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://raw.githubusercontent.com/cosmic-hydra/revOS/main/gap-ledger/schema.json",
  "title": "revOS Gap Ledger Record",
  "description": "One record per gap between the shipped macOS behaviour and the upstream OSS implementation it is gap-closed against. Conforms to evidence/schema.json conventions.",
  "type": "object",
  "required": [
    "gap_id",
    "subsystem",
    "gap_statement",
    "evidence_refs",
    "upstream",
    "reverification",
    "route",
    "implementation_ref",
    "test_refs",
    "status"
  ],
  "additionalProperties": false,
  "properties": {
    "gap_id": {
      "type": "string",
      "minLength": 1,
      "pattern": "^[a-z0-9][a-z0-9-]*$"
    },
    "subsystem": {
      "enum": ["cf-types", "cf-runtime", "libdispatch", "foundation-bridge"]
    },
    "gap_statement": {
      "type": "string",
      "minLength": 1
    },
    "evidence_refs": {
      "type": "array",
      "minItems": 1,
      "items": { "type": "string", "minLength": 1 }
    },
    "upstream": {
      "type": "object",
      "required": ["repo", "pinned_commit", "verified_at"],
      "additionalProperties": false,
      "properties": {
        "repo": { "type": "string", "minLength": 1 },
        "pinned_commit": { "type": "string", "pattern": "^[0-9a-f]{40}$" },
        "pinned_tag": { "type": "string" },
        "verified_at": { "type": "string", "minLength": 1 },
        "head_commit": { "type": "string", "pattern": "^[0-9a-f]{40}$" },
        "head_verified_at": { "type": "string" }
      }
    },
    "reverification": {
      "type": "object",
      "required": ["status", "method", "result"],
      "additionalProperties": false,
      "properties": {
        "status": {
          "enum": ["still-open", "closed-upstream", "never-existed", "drifted", "not-yet-checked"]
        },
        "method": { "type": "string", "minLength": 1 },
        "result": { "type": "string", "minLength": 1 }
      }
    },
    "route": {
      "enum": ["shim", "in-place-patch", "from-scratch", "undecided"]
    },
    "implementation_ref": {
      "type": "object",
      "additionalProperties": false,
      "properties": {
        "file": { "type": "string" },
        "symbol": { "type": "string" },
        "commit": { "type": "string", "pattern": "^[0-9a-f]{40}$" }
      }
    },
    "test_refs": {
      "type": "array",
      "items": { "type": "string", "minLength": 1 }
    },
    "status": {
      "enum": ["open", "in-progress", "implemented", "verified", "dropped"]
    }
  }
}
```

- [ ] **Step 2: Write the validator**

Create `scripts/lib/validate_gap_ledger.py` with content:

```python
#!/usr/bin/env python3
"""Validate every gap-ledger record under gap-ledger/gaps/ and enforce the
five invariants from the revOS production-reimplementation design spec.

Usage:
  scripts/lib/validate_gap_ledger.py [ROOT_DIR] [--write-index]

ROOT_DIR defaults to the repository root (the parent of gap-ledger/).
--write-index regenerates gap-ledger/index.json from the per-gap files.

Exit codes:
  0  all gap records conform and all invariants hold
  1  at least one violation (one line per violation on stdout)
  2  schema load failure
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Reuse the JSON-Schema subset walker from the evidence validator rather than
# duplicating it. Both live in scripts/lib/, so Python puts that directory on
# sys.path[0] when this file is invoked as a script. One implementation means
# one set of semantics for 'required', 'additionalProperties', 'pattern', and
# the rest.
from validate_evidence import _walk

SCHEMA_FILE = Path(__file__).resolve().parent.parent.parent / "gap-ledger" / "schema.json"
GAPS_DIRNAME = "gaps"
INDEX_FILE = "index.json"


def load_schema() -> dict[str, Any]:
    with SCHEMA_FILE.open() as fh:
        return json.load(fh)


def iter_gap_files(root: Path) -> list[Path]:
    gaps = root / GAPS_DIRNAME
    if not gaps.is_dir():
        return []
    return sorted(p for p in gaps.glob("*.json") if p.name != INDEX_FILE)


def check_invariants(record: dict[str, Any], path: Path, root: Path) -> list[str]:
    """The five invariants from spec section 5.2."""
    errors: list[str] = []
    tag = path.name

    # 1. Every evidence_refs entry resolves to a real, schema-valid record.
    for ref in record.get("evidence_refs", []):
        target = root / ref
        if not target.is_file():
            errors.append(f"{tag}: evidence_refs entry does not resolve to a file: {ref}")

    # 2. A gap that is not 'open' must have a recorded reverification result.
    status = record.get("status")
    reverification = record.get("reverification", {})
    if status != "open":
        if not reverification.get("result", "").strip():
            errors.append(f"{tag}: status={status!r} requires a non-empty reverification.result")

    # 3. A gap that is implemented or verified needs an implementation and a test.
    if status in {"implemented", "verified"}:
        impl = record.get("implementation_ref", {})
        if not impl.get("file"):
            errors.append(f"{tag}: status={status!r} requires implementation_ref.file")
        if not record.get("test_refs"):
            errors.append(f"{tag}: status={status!r} requires at least one test_refs entry")

    # 4. A closed-upstream gap must be dropped.
    if reverification.get("status") == "closed-upstream" and status != "dropped":
        errors.append(
            f"{tag}: reverification.status='closed-upstream' requires status='dropped', got {status!r}"
        )

    # 5. A not-yet-checked gap must not claim to be implemented.
    if reverification.get("status") == "not-yet-checked" and status in {"implemented", "verified"}:
        errors.append(
            f"{tag}: reverification.status='not-yet-checked' cannot coexist with status={status!r}"
        )
    return errors


def write_index(root: Path) -> None:
    entries = []
    for path in iter_gap_files(root):
        with path.open() as fh:
            record = json.load(fh)
        entries.append(
            {
                "gap_id": record.get("gap_id"),
                "subsystem": record.get("subsystem"),
                "route": record.get("route"),
                "status": record.get("status"),
                "reverification_status": record.get("reverification", {}).get("status"),
                "file": str(path.relative_to(root)),
            }
        )
    entries.sort(key=lambda e: (e.get("subsystem") or "", e.get("gap_id") or ""))
    out = root / GAPS_DIRNAME / INDEX_FILE
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        json.dump({"gaps": entries, "count": len(entries)}, fh, indent=2, sort_keys=True)
        fh.write("\n")


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    write_index = "--write-index" in argv
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parent.parent.parent

    try:
        schema = load_schema()
    except Exception as exc:  # noqa: BLE001
        print(f"schema load failure: {exc}", file=sys.stderr)
        return 2

    files = iter_gap_files(root)
    if not files:
        print(f"no gap records found under {root}/{GAPS_DIRNAME}/")
        if write_index:
            write_index(root)
        return 0

    failures: list[tuple[Path, list[str]]] = []
    successes = 0
    for path in files:
        try:
            with path.open() as fh:
                payload = json.load(fh)
        except json.JSONDecodeError as exc:
            failures.append((path, [f"json decode error: {exc}"]))
            continue
        errors = _walk(payload, schema, path.name)
        if not errors:
            errors = check_invariants(payload, path, root)
        if errors:
            failures.append((path, errors))
        else:
            successes += 1

    if write_index:
        write_index(root)

    for path, errors in failures:
        for err in errors:
            print(f"FAIL {path.name}: {err}")
    total = successes + len(failures)
    print(f"validated {total} gap records: {successes} ok, {len(failures)} failing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 3: Create the gaps directory**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
mkdir -p gap-ledger/gaps
touch gap-ledger/gaps/.gitkeep
```

- [ ] **Step 4: Verify the validator passes on an empty ledger**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
python3 scripts/lib/validate_gap_ledger.py .
```
Expected: `no gap records found under …/gap-ledger/gaps/` and exit code 0.

- [ ] **Step 5: Write a fixture gap and verify it passes**

Create `gap-ledger/gaps/cf-string-tagged-pointer.json` with content:

```json
{
  "gap_id": "cf-string-tagged-pointer",
  "subsystem": "cf-types",
  "gap_statement": "macOS 27 exports a CFString tagged-pointer fast path that CF-Lite 1153.18 does not contain.",
  "evidence_refs": [
    "subsystems/cf-types/evidence/cfstringcreatetaggedpointerstring.json"
  ],
  "upstream": {
    "repo": "apple-oss-distributions/CF",
    "pinned_commit": "dc54c6bb1c1e5e0b9486c1d26dd5bef110b20bf3",
    "pinned_tag": "CF-1153.18",
    "verified_at": "2026-10-21"
  },
  "reverification": {
    "status": "not-yet-checked",
    "method": "Phase 0b re-verification against upstream HEAD",
    "result": "Scheduled for Phase 0b."
  },
  "route": "undecided",
  "implementation_ref": {},
  "test_refs": [],
  "status": "open"
}
```

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
python3 scripts/lib/validate_gap_ledger.py .
```
Expected: `validated 1 gap records: 1 ok, 0 failing` and exit code 0.

The `evidence_refs` path above is the real filename on disk
(`cfstringcreatetaggedpointerstring.json` — the `cf-types` agent used plain
names, while the `cf-runtime` agent used hash suffixes, so the two
subsystems' evidence filenames do not share a convention). If it does not
resolve, list the actual filenames with
`ls subsystems/cf-types/evidence/` and correct the reference. The invariant
is real and must not be weakened to make the fixture pass.

- [ ] **Step 6: Verify each invariant actually fires**

Run this, which must fail with exactly the expected violations:
```bash
cd /Users/vaithianathan/revOS-work/revOS
cat > gap-ledger/gaps/_fixture-violations.json <<'EOF'
{
  "gap_id": "fixture-violations",
  "subsystem": "libdispatch",
  "gap_statement": "fixture",
  "evidence_refs": ["subsystems/libdispatch/evidence/does-not-exist.json"],
  "upstream": {
    "repo": "apple-oss-distributions/libdispatch",
    "pinned_commit": "2361ffb78a76f7ee488cd052eb0bc5c767118bf9",
    "verified_at": "2026-10-21"
  },
  "reverification": {
    "status": "closed-upstream",
    "method": "fixture",
    "result": "fixture"
  },
  "route": "shim",
  "implementation_ref": {},
  "test_refs": [],
  "status": "implemented"
}
EOF
python3 scripts/lib/validate_gap_ledger.py . ; echo "exit: $?"
```
Expected: exit 1, and violations for — the unresolvable `evidence_refs` entry, `closed-upstream` requiring `dropped`, and `status='implemented'` requiring `implementation_ref.file` and a `test_refs` entry. Then remove the fixture:
```bash
rm gap-ledger/gaps/_fixture-violations.json
```

- [ ] **Step 7: Verify `--write-index` generates the index**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
python3 scripts/lib/validate_gap_ledger.py . --write-index
cat gap-ledger/gaps/index.json
```
Expected: JSON with `count: 1` and one entry for `cf-string-tagged-pointer`.

- [ ] **Step 8: Commit**

```bash
cd /Users/vaithianathan/revOS-work/revOS
git add gap-ledger/schema.json gap-ledger/gaps scripts/lib/validate_gap_ledger.py
git diff --cached --name-only
git commit -m "feat(harness): add the gap-ledger schema and validator

The gap ledger is the bridge between the evidence world and the code world:
one file per gap, recording the evidence that proves it, the upstream state
it was measured against, a re-verification result, the chosen implementation
route, and the tests that cover it.

Per-gap files rather than one index so parallel agents never contend on a
shared file; index.json is generated by --write-index and cannot drift.

The validator enforces the five spec invariants. The load-bearing one: a
gap whose reverification.status is 'closed-upstream' must have status
'dropped'. We do not implement gaps that no longer exist.

One fixture gap is included (cf-string-tagged-pointer) with
reverification.status='not-yet-checked'; Phase 0b resolves it."
# Do not push. The controller reviews this branch and merges it to `main`
# after the task review passes.
```

---

### Task 7: Wire CI, add a local CI runner, and lay down release scaffolding

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `scripts/lib/validate_wrapper_output.py`
- Create: `scripts/bin/revos-ci`
- Create: `VERSION`
- Create: `CHANGELOG.md`
- Modify: `AGENTS.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: every artifact produced by Tasks 1–5.
- Produces: `scripts/bin/revos-ci` — a local mirror of the CI job list, exit 0 when every check passes. `VERSION` — a single semver line, `0.1.0`. `CHANGELOG.md` — Keep-a-Changelog format.

- [ ] **Step 1: Create `VERSION`**

Create `VERSION` with content:
```
0.1.0
```

- [ ] **Step 2: Create `CHANGELOG.md`**

Create `CHANGELOG.md` with content:

```markdown
# Changelog

All notable changes to revOS are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Nothing yet.

## [0.1.0] - 2026-10-21

### Added

- Harness: evidence schema, six analysis wrappers, CI job definitions, and the
  agent team protocol.
- Sprint-1 reverse-engineering evidence: 76 records across four subsystems —
  `cf-types` (23), `cf-runtime` (26), `foundation-bridge` (14), `libdispatch` (12).
- `dyld-info-exports` wrapper for cache-backed images. On macOS 27 the system
  frameworks are dangling symlinks into the arm64e dyld shared cache; this
  reads their export trie in place.
- `capability-probe` wrapper classifying symbols as works / traps / missing /
  private.
- Cache-backed image detection: `nm-symbols` now falls back to the export trie
  and reports `source_tool=dyld_info`.
- Gap-ledger schema and validator, enforcing the five invariants from the
  production-reimplementation design spec.
- Design spec: `docs/superpowers/specs/2026-10-21-revos-production-reimplementation-design.md`.

### Fixed

- CI `lint-shell` job was red on every commit: it fed `output-schema.json` and
  `validate_evidence.py` to shellcheck and its `||` fallback re-ran the same
  failing command. It now selects shell files by bash shebang.

### Known limitations

- No decompiler is available on this host (no Hopper, Ghidra, IDA, or radare2),
  so all analysis is static-table or black-box behavioural.
- `class-dump` is not in Homebrew; ObjC class enumeration uses
  `class_copyMethodList` via the objc4 runtime instead.
- The `foundation-bridge` evidence records were captured against
  swift-corelibs-foundation at `b40c41e7`; re-verification against upstream
  HEAD is scheduled for Phase 0b.

[Unreleased]: https://github.com/cosmic-hydra/revOS/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/cosmic-hydra/revOS/releases/tag/v0.1.0
```

- [ ] **Step 2b: Create the wrapper-output validator**

Nothing currently validates a wrapper's output against `scripts/bin/output-schema.json`.
That is why Task 2 could ship `tool: "dyld_info"` — a value the schema's enum
forbids — without anything noticing. The contract is documentation-by-convention
only. Close it.

Create `scripts/lib/validate_wrapper_output.py` with content:

```python
#!/usr/bin/env python3
"""Validate one wrapper envelope against scripts/bin/output-schema.json.

Usage:
  scripts/lib/validate_wrapper_output.py <envelope.json> [<envelope.json> ...]

Reuses the JSON-Schema subset walker from validate_evidence.py so the two
validators share one set of semantics. Exit 0 when every envelope conforms,
1 when any envelope violates the schema.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from validate_evidence import _walk

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "bin" / "output-schema.json"


def load_schema() -> dict[str, Any]:
    with SCHEMA_FILE.open() as fh:
        return json.load(fh)


def main(argv: list[str]) -> int:
    paths = argv[1:]
    if not paths:
        print("usage: validate_wrapper_output.py <envelope.json> [...]", file=sys.stderr)
        return 2
    try:
        schema = load_schema()
    except Exception as exc:  # noqa: BLE001
        print(f"schema load failure: {exc}", file=sys.stderr)
        return 2

    failures = 0
    for raw_path in paths:
        path = Path(raw_path)
        try:
            with path.open() as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"FAIL {path.name}: cannot read envelope: {exc}")
            failures += 1
            continue
        errors = _walk(payload, schema, path.name)
        if errors:
            failures += 1
            for err in errors:
                print(f"FAIL {path.name}: {err}")
        else:
            print(f"ok {path.name}")
    print(f"validated {len(paths)} wrapper envelopes: {len(paths) - failures} ok, {failures} failing")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
```

- [ ] **Step 2c: Add a wrapper-output job to `revos-ci` and to CI**

In `scripts/bin/revos-ci`, add a job that runs every wrapper against a control
binary and validates each envelope:

```bash
job_validate_wrapper_output() {
  local tmpdir
  tmpdir=$(mktemp -d)
  trap 'rm -rf "$tmpdir"' RETURN
  local control=/usr/lib/system/libsystem_pthread.dylib
  local n=0
  for w in scripts/bin/*; do
    [[ -x "$w" ]] || continue
    case "$(basename "$w")" in
      rea-call) continue ;;   # needs network + npx; covered by no gate today
      revos-ci) continue ;;   # this script
    esac
    bash "$w" "$control" > "$tmpdir/$(basename "$w").json" 2>/dev/null || true
    n=$((n + 1))
  done
  python3 scripts/lib/validate_wrapper_output.py "$tmpdir"/*.json
}
```

and register it in the `run_job` list:

```bash
run_job validate-wrapper-output job_validate_wrapper_output
```

Add the matching CI job:

```yaml
  validate-wrapper-output:
    name: wrapper envelopes conform to output-schema.json
    runs-on: macos-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Validate wrapper envelopes
        run: |
          set -euo pipefail
          tmpdir=$(mktemp -d)
          for w in scripts/bin/*; do
            [ -x "$w" ] || continue
            case "$(basename "$w")" in
              rea-call) continue ;;
              revos-ci) continue ;;
            esac
            bash "$w" /usr/lib/system/libsystem_pthread.dylib > "$tmpdir/$(basename "$w").json" 2>/dev/null || true
          done
          python3 scripts/lib/validate_wrapper_output.py "$tmpdir"/*.json
```

This job must run on `macos-latest`, not `ubuntu-latest`: the control binary
`/usr/lib/system/libsystem_pthread.dylib` is macOS-specific.

- [ ] **Step 3: Create the local CI runner**

Create `scripts/bin/revos-ci` with content:

```bash
#!/usr/bin/env bash
# scripts/bin/revos-ci
#
# A local mirror of the CI job list. Every check here also runs in
# .github/workflows/ci.yml. Run this before pushing.
#
# Usage: revos-ci [--help] [--only=JOB,JOB]
set -eu
cd "$(dirname "$0")/../.."

only=""
for arg in "$@"; do
  if [[ "$arg" == "--help" || "$arg" == "-h" ]]; then
    cat <<EOF
revos-ci — run the revOS CI checks locally.

Usage:
  scripts/bin/revos-ci [--only=JOB,JOB]

Jobs: shellcheck, validate-evidence, validate-gap-ledger, license-check

Exit codes: 0 all selected jobs passed, 1 at least one failed
EOF
    exit 0
  fi
  if [[ "$arg" == --only=* ]]; then only="${arg#--only=}"; fi
done

failures=0
run_job() {
  local name="$1"
  shift
  if [[ -n "$only" ]] && ! printf '%s' ",$only," | grep -q ",$name,"; then
    echo "== SKIP $name"
    return 0
  fi
  echo "== $name"
  if "$@"; then
    echo "== PASS $name"
  else
    echo "== FAIL $name"
    failures=$((failures + 1))
  fi
}

job_shellcheck() {
  local files
  files=$(grep -rlI '^#!/usr/bin/env bash' scripts/ | sort)
  command -v shellcheck >/dev/null 2>&1 || { echo "shellcheck not installed"; return 1; }
  shellcheck --severity=warning --exclude=SC1091 $files
}

job_validate_evidence() {
  python3 scripts/lib/validate_evidence.py .
}

job_validate_gap_ledger() {
  python3 scripts/lib/validate_gap_ledger.py .
}

job_license_check() {
  local missing=0
  for d in third_party/*/; do
    [ -d "$d" ] || continue
    name=$(basename "$d")
    if ! ls "$d" | grep -qiE '^(LICENSE|COPYING|APPLE_LICENSE)'; then
      echo "missing licence file in third_party/$name"
      missing=1
    fi
  done
  return $missing
}

run_job shellcheck job_shellcheck
run_job validate-evidence job_validate_evidence
run_job validate-gap-ledger job_validate_gap_ledger
run_job license-check job_license_check

if [[ $failures -gt 0 ]]; then
  echo "FAILED: $failures job(s)"
  exit 1
fi
echo "OK: all jobs passed"
```

- [ ] **Step 4: Make it executable and run it**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
chmod +x scripts/bin/revos-ci
bash scripts/bin/revos-ci
```
Expected: every job reports `PASS` and the script prints `OK: all jobs passed`, exit 0. The `license-check` job passes when `third_party/` is empty or every vendored tree carries a licence file — it must not fail the run today.

- [ ] **Step 4b: Add a three-shape wrapper fixture**

The Task 3 reviewer noted that the single highest-value case — a dangling
symlink that is NOT cache-resident must stay `tool-failed` rather than being
misreported as `cache-backed` — has no automated guard, because the repo has no
`tests/` directory. Once `scripts/lib/validate_wrapper_output.py` exists, add
the fixture beside it so that shape cannot regress silently.

Create `scripts/lib/fixtures/wrapper_shapes.sh`:

```bash
#!/usr/bin/env bash
# scripts/lib/fixtures/wrapper_shapes.sh
#
# Three input shapes a wrapper must handle differently:
#   1. a real on-disk dylib          -> status ok
#   2. a cache-backed framework stub -> status ok via the dyld_info fallback
#   3. a dangling symlink to nowhere  -> status tool-failed
#
# The third is the regression guard: it must NOT be reported as cache-backed.
# Usage: scripts/lib/fixtures/wrapper_shapes.sh <wrapper>
set -eu

wrapper="${1:?usage: wrapper_shapes.sh <wrapper>}"
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

real=/usr/lib/system/libsystem_pthread.dylib
stub=/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation
dangling="$tmpdir/dangling"
ln -sf /nonexistent-target "$dangling"

status_of() {
  bash "$wrapper" "$1" 2>/dev/null | jq -r '.status' 2>/dev/null || echo "unparseable"
}

printf '  real      %-58s %s\n' "$real" "$(status_of "$real")"
printf '  cache     %-58s %s\n' "$stub" "$(status_of "$stub")"
printf '  dangling  %-58s %s\n' "$dangling" "$(status_of "$dangling")"
```

Expected on this host: `ok`, `ok`, `tool-failed`. A `cache-backed` status for the
dangling path is a defect.

- [ ] **Step 5: Extend the CI workflow with the new jobs**

In `.github/workflows/ci.yml`, add these two jobs after the existing `validate-evidence` job:

```yaml
  validate-gap-ledger:
    name: validate gap-ledger records
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Run validator
        run: |
          python3 scripts/lib/validate_gap_ledger.py .

  license-check:
    name: every vendored tree carries a licence
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Check third_party licences
        run: |
          set -euo pipefail
          missing=0
          for d in third_party/*/; do
            [ -d "$d" ] || continue
            name=$(basename "$d")
            if ! ls "$d" | grep -qiE '^(LICENSE|COPYING|APPLE_LICENSE)'; then
              echo "::error::missing licence file in third_party/$name"
              missing=1
            fi
          done
          exit $missing
```

- [ ] **Step 6: Document the worktree protocol in `AGENTS.md`**

Append to `AGENTS.md`, after the `## Rebase-on-push policy` section:

```markdown
## Worktree isolation (mandatory from Phase 0a onward)

Sprint 1 ran every agent in ONE shared working tree. Agents clobbered each
other's git index: a `git add` by one agent swept up another agent's staged
files, and a `git reset` by a third unstaged them. One commit failed because
of it, and one nearly lost a milestone's entire output.

**Every agent now works in its own git worktree.** The orchestrator creates
the worktree and tells the agent its absolute path. Inside a worktree:

```bash
git worktree add /abs/path/to/agent-<name> -b agent/<name> origin/main
```

Rules:

- An agent MUST NOT `cd` into the shared checkout, and MUST NOT run
  `git add -A`, `git add .`, or `git stash` — those are the exact operations
  that caused the sprint-1 collisions.
- An agent stages ONLY the paths its brief names, and runs
  `git diff --cached --name-only` to confirm before committing.
- An agent never rebases onto, merges, or pushes `main`. It pushes its own
  branch and reports the commit hash; the integrator merges to `main`.
- If a push fails with non-fast-forward, the agent rebases ITS OWN branch
  onto `origin/main` and retries once. It never force-pushes.
```

- [ ] **Step 7: Update the README's tooling section**

In `README.md`, find the tooling paragraph and append this after it:

```markdown
### Cache-backed system frameworks

On macOS 27 the system frameworks are **not Mach-O files on disk**.
`/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation` is a
dangling symlink; the real image is resident in the arm64e dyld shared cache.
`nm` and `otool` cannot open such a path, and report "No such file or
directory" — which reads as *the library is gone* rather than *the library is
not a file*.

The harness handles this explicitly:

- `scripts/bin/dyld-info-exports` reads the export trie in place, via
  `dyld_info -exports`. It works on cache-backed and ordinary dylibs alike.
- `scripts/bin/nm-symbols` detects a cache-backed image and falls back to the
  export trie, reporting `source_tool: "dyld_info"` so the provenance is
  explicit.
- `scripts/bin/otool-exports` reports a distinct `status: "cache-backed"`
  rather than a misleading failure.

Verified: CoreFoundation on macOS 27 / arm64e yields 3098 exports, matching
the count independently recorded by the `cf-types` agent.
```

- [ ] **Step 8: Run the full local CI and the evidence validator**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
bash scripts/bin/revos-ci
python3 scripts/lib/validate_evidence.py . | tail -1
```
Expected: `OK: all jobs passed` and `validated 76 evidence records: 76 ok, 0 failing`.

- [ ] **Step 9: Commit**

```bash
cd /Users/vaithianathan/revOS-work/revOS
git add .github/workflows/ci.yml scripts/bin/revos-ci VERSION CHANGELOG.md AGENTS.md README.md
git diff --cached --name-only
git commit -m "chore(harness): wire CI, add a local CI runner, and lay down release scaffolding

- ci.yml gains validate-gap-ledger and license-check jobs.
- scripts/bin/revos-ci mirrors the CI job list locally, so the same checks
  can be run before pushing.
- VERSION (0.1.0) and CHANGELOG.md establish the release trail, recording the
  sprint-1 evidence, the harness additions, and the known limitations
  (no decompiler, no class-dump, pending Phase 0b re-verification).
- AGENTS.md now mandates a git worktree per agent, with the reasoning spelled
  out: sprint 1's shared tree let agents clobber each other's index, which
  cost one commit and nearly a milestone.
- README documents the cache-backed framework situation and the wrappers that
  handle it."
# Do not push. The controller reviews this branch and merges it to `main`
# after the task review passes.
```

- [ ] **Step 10: Verify CI is green on the remote**

Run:
```bash
cd /Users/vaithianathan/revOS-work/revOS
# Do not push. The controller reviews this branch and merges it to `main`
# after the task review passes.
gh run list --repo cosmic-hydra/revOS --limit 3
```
Expected: the newest run reports `completed success`. If the `lint-shell` job still fails, run the exact CI command locally and fix before pushing again — do not merge red.

---

## Self-Review

**Spec coverage.** Every Phase 0a requirement from spec §4.1 maps to a task:
CI repair → Task 1; `dyld-info-exports` → Task 2; cache-backed detection → Task 3;
`dyld_info` in the schema enum → Task 4; `capability-probe` → Task 4; host-native
default slice + corpus slice-attribution audit + record correction → Task 5;
gap-ledger schema + validator → Task 6; CI wiring, local runner, release
scaffolding, and the worktree protocol → Task 7. All eight bullet points of §4.1
are covered, plus the corpus-correction work that Task 2's review exposed.

**Out of scope for this plan (deliberately).** The `dyld-info-exports` wrapper
used by Task 3 exists by the end of Task 2, so Task 3 can depend on it.

The gap-ledger validator **imports** the JSON-Schema subset walker from
`validate_evidence.py` rather than copying it. The two validators have
different schemas and different invariants — those stay separate — but the
schema-walking semantics ('required', 'additionalProperties', 'pattern',
'minLength', 'minItems', 'enum') must not drift apart. The import was verified
to work both when `scripts/lib/validate_gap_ledger.py` is invoked directly
(Python puts the script's directory on `sys.path[0]`) and when the module is
loaded via `importlib` from another working directory. `validate_evidence.py`
is side-effect free at import time — its only module-level statement is the
`if __name__ == "__main__"` guard.

**Placeholder scan.** No `TBD`, `TODO`, "implement later", or "similar to
Task N". Every code block contains the literal content to write. Every command
contains the literal command to run, with its expected output and the specific
failure signature to look for.

**Type consistency.** `is_cache_backed` returns a shell exit status, not a
value. `assert_binary_present` sets `BIN_VALID` to one of `ok`, `cache-backed`,
`missing` — the same three values Task 3's wrappers branch on. `emit_cache_backed`
takes `(tool, binary, hint)` and matches the existing `(tool, binary, msg)`
convention of `emit_tool_failed`. `dyld-info-exports` emits `observations.arch`,
`observations.exports`, `observations.total`; Task 3's fallback maps `exports` to
`observations.symbols` with `kind: "T"`, which is the shape `nm-symbols` already
produced, so downstream consumers of `nm-symbols` output are unaffected.
`capability-probe` emits `observations.symbols` with `{name, status}` and
`observations.summary` with the four status counters. The gap-ledger schema's
`reverification.status` enum is `still-open | closed-upstream | never-existed |
drifted | not-yet-checked`, and Task 5's invariant 4 checks `closed-upstream`
against `status: "dropped"` — the same pairing the spec states in §5.2.

**Known uncertainty, called out rather than hidden.** Task 4's `capability-probe`
classifies `works` / `missing` / `private` statically and never assigns `traps`;
the `traps` state is reserved for the Phase 0c runtime probe harness, which is
out of scope for this plan. The `--help` text says so explicitly. A reviewer
should not expect `traps` to be populated by this task.

**Plan amendments, made mid-execution.** Two defects were found by the Task 1
implementer and corrected here rather than in the code, because both were
errors in the plan's own expectations:

1. Task 1 Step 7 expected a non-zero `observations.total` for the filter
   `^_CF` against `libsystem_pthread.dylib`. That dylib exports 209 symbols,
   139 of them `_pthread*` and **none** `_CF*`, so a `^_CF` filter correctly
   returns 0. The expectation was wrong, not the wrapper. The step now uses
   `^_pthread` and expects 139. The implementer correctly refused to
   substitute a different binary to make the number look right.
2. Every task's commit step ended with `git push origin main`, inherited from
   the direct-commit workflow this plan was first drafted against. Under the
   branch-and-review workflow the plan actually executes, an implementer
   commits to its branch and the controller merges to `main` after the task
   review passes. The commit steps now say so.
3. The Task 3 fallback's jq program omitted `binary`, which
   `scripts/bin/output-schema.json` lists as REQUIRED. The literal plan code
   therefore emitted a schema-invalid envelope. The implementer added
   `binary: .binary` and demonstrated that the brief's version fails the
   repo's own `_walk` with "missing required key 'binary'".
4. `scripts/bin/otool-exports` was the only wrapper that exited **0** on
   `status: "tool-failed"`; `nm-symbols`, `strings-grep`, `class-dump-types`
   and `dyld-info-exports` all exit **1**. Task 3's brief changed it to
   `exit 1`, which makes it conform to the house convention rather than
   diverge from it. The implementer flagged the behaviour change rather than
   making it silently.
5. The Task 3 fallback's jq program dropped `observations.arch` while the
   brief's own Note required the fallback to "pass through whatever `arch`
   and `exports` the wrapper reports" — the brief contradicted itself between
   its prose and its code block. The code block was the defect. `arch` is now
   passed through, and `exit_code` is hard-coded 0 because the guard has
   already proven `status == "ok"`.
6. `nm-symbols` had a second `tool-failed` site — the `nm -gU failed` branch —
   that exited **0** while its envelope claimed `exit_code: 1`. Now exits 1,
   matching every other tool-failed path. (`emit_tool_missing` exiting 0 is a
   separate, deliberate house convention, consistent across all wrappers, and
   is left alone.)
7. The Task 4 brief **re-introduced the exact slice-mixing bug** that Task 2's
   review had just caught in `dyld-info-exports`: its `capability-probe` parse
   collected every slice of a universal binary without bounding to one section
   (`/bin/ls` → total 2, distinct 1). The Task 4 implementer caught it
   independently by testing a universal binary. A second copy of the export-trie
   parser is a second place for the slice logic to drift, so Task 5 now makes
   `capability-probe` **delegate** to `dyld-info-exports` rather than re-parsing
   the trie — one place owns "which slice, which exports", and the host-native
   default applies to both wrappers at once.
8. The Task 4 brief's Step 2 was **a verification that verified nothing**: the
   schema-acceptance probe record was placed outside `subsystems/`, the only tree
   `validate_evidence.py` scans, so the command exited 0 having checked zero
   records. The implementer noticed and re-ran it with the record in place.
9. The Task 3 re-review surfaced a **second, different** corpus defect: 26
   `cf-runtime` records plus 1 `foundation-bridge` record describe the
   *pre-Task-3* wrapper behaviour in their `observation.summary` ("nm-symbols
   and otool-exports both return status=tool-failed against this path"). That
   was true when observed and is false now. Unlike the slice contamination,
   the quoted output and the `reproducer` are **still correct and still
   reproduce exactly** — only the prose is stale. Task 5 now audits and
   corrects this as a second dimension, and the audit tool gained a
   `STALE-NARRATIVE` check so the class cannot recur.

10. The Task 4 review found three more defects in the brief's `capability-probe`
    code, all now fixed: the envelope carried **no slice label** (so a
    `missing` verdict meant "absent from the x86_64 slice" with nothing
    downstream able to tell); an **empty or comment-only `--symbols` file
    silently discarded the flag** and returned the entire export trie (3098
    unrequested verdicts instead of 0, because the guard tested the filtered
    content rather than the flag); and **space-separated flags mis-parsed** while
    the `--help` advertised an exit code the wrapper could never return. Three
    Minors folded into the same fix round: `__mh_*` (a public Mach-O/dyld ABI
    constant) was classified `private`, so a system executable's entire output
    was mislabeled; a changed `dyld_info` output shape would report
    `ok, total 0` instead of failing; and the per-symbol loop spawned ~3
    processes per symbol, which is pathological at the scale Task 5's audit
    tool needs.

**Every `jq` program in this plan was executed against real output before the
plan was committed.** Three defects were found and fixed in the process, and the
corrections are baked into the task text above:

1. The `public_names` list in `capability-probe` originally included
   `__`-prefixed names, which made the `private` branch unreachable — every
   Apple-private symbol would have been classified `works`. `public_names` now
   excludes `__`-prefixed names, and Task 4 Step 6 asserts all three static
   states with a symbol set verified to produce `works` / `missing` / `private`.
2. Task 1 Step 5 originally carried two competing versions of the CI `run:`
   block, one of which contained a stray `mapfile_placeholder` line. There is
   now exactly one version.
3. The `dyld_info` parse was confirmed to yield **3098** exports for the arm64e
   CoreFoundation slice — the same count the `cf-types` agent independently
   recorded — and the arch header parse was confirmed to yield `arm64e`. The
   `--arch x86_64` request still reports `arm64e`, which is why the reported
   arch is parsed from the output header rather than the flag.

**Cross-validation built into the plan.** Task 4 Step 6 asserts that
`_CFGetRetainCount` is `works` while `_CFRetainCount` is `missing`, and that
`__CFStringCreateTaggedPointerString` is `private` at offset `0x0016E624`. Both
are independent re-derivations of sprint-1 findings: the `cf-types` agent
recorded that the public symbol is `CFGetRetainCount` and that the tagged-pointer
creator sits at `0x0016E624`. If the harness ever disagrees with the evidence
corpus, this assertion is where it surfaces.
