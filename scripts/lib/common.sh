#!/usr/bin/env bash
# scripts/lib/common.sh — shared helpers for scripts/bin/* wrappers.
# Source me; do not execute me directly.
#
# Every wrapper in scripts/bin/* MUST:
#   source "$(dirname "$0")/../lib/common.sh"
#   parse_tool_args "$@"
#   emit_ok "otool" "$BINARY" '{"linked":[...],"exports":[...]}'
#   # or
#   emit_tool_missing "class-dump" "$BINARY" "brew install class-dump"
#   # or
#   emit_tool_failed "nm" "$BINARY" "exit=1 msg=..."
#
# All wrappers emit a single JSON object conforming to scripts/bin/output-schema.json.

set -u
set -o pipefail

# ---- timing -------------------------------------------------------------
_now_ms() {
  # Portable millisecond clock. macOS `date +%s%N` lacks %N on BSD coreutils,
  # so prefer python3 (always available in CI on this repo).
  if command -v python3 >/dev/null 2>&1; then
    python3 -c 'import time; print(int(time.time() * 1000))'
  else
    # Fallback: second-resolution. Wrappers will still run.
    printf '%d' "$(date +%s)"
  fi
}

# ---- argument parsing ---------------------------------------------------
# Result variables set by parse_tool_args:
#   BINARY         path the wrapper was asked to inspect (may be empty)
#   WRAPPER_OPTS   associative array of --foo / --foo=bar options captured
#   POSITIONAL     remaining positional args
#
# Usage: parse_tool_args "$@"
parse_tool_args() {
  BINARY=""
  POSITIONAL=()
  WRAPPER_OPTS=()
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --help|-h)
        cat <<EOF
usage: $(basename "$0") [--help] [--format=<text|json>] [<binary-path>]

Common flag: --format json (default) emits the contract from scripts/bin/output-schema.json.

Inspect <binary-path> (a Mach-O / dylib / framework). Emits one JSON document
on stdout. On a missing or non-Mach-O file the wrapper emits status=tool-failed.
EOF
        exit 0
        ;;
      --format=*)
        WRAPPER_FORMAT="${1#--format=}"
        shift
        ;;
      --format)
        shift
        WRAPPER_FORMAT="${1:-json}"
        shift
        ;;
      --)
        shift
        while [[ $# -gt 0 ]]; do POSITIONAL+=("$1"); shift; done
        ;;
      -*)
        # Unknown flag. Capture verbatim so wrappers can decide.
        WRAPPER_OPTS+=("$1")
        shift
        ;;
      *)
        POSITIONAL+=("$1")
        shift
        ;;
    esac
  done
  if [[ ${#POSITIONAL[@]} -ge 1 ]]; then
    BINARY="${POSITIONAL[0]}"
  fi
  WRAPPER_FORMAT="${WRAPPER_FORMAT:-json}"
}

# ---- json emit helpers -------------------------------------------------
# Emit a success envelope. $1=tool, $2=binary, $3=observations_json_object
# (already a JSON object literal, e.g. '{"linked":[],"exports":[]}').
emit_ok() {
  local tool="$1"
  local binary="$2"
  local observations="$3"
  local start="$WRAPPER_START_MS"
  local now
  now="$(_now_ms)"
  local duration=0
  if [[ -n "${start:-}" ]]; then duration=$(( now - start )); fi
  jq -n \
    --arg tool "$tool" \
    --arg binary "$binary" \
    --argjson observations "$observations" \
    --argjson duration "$duration" \
    '{tool: $tool, binary: $binary, status: "ok", exit_code: 0, duration_ms: $duration, observations: $observations}'
}

# Emit a tool-not-installed envelope. $3 is an install hint string.
emit_tool_missing() {
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
    '{tool: $tool, binary: $binary, status: "tool-not-installed", exit_code: 127, duration_ms: $duration, error: ("tool not on PATH; install with: " + $hint)}'
}

# Emit a tool-failed envelope. $3 is the failure message.
emit_tool_failed() {
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
    '{tool: $tool, binary: $binary, status: "tool-failed", exit_code: 1, duration_ms: $duration, error: $msg}'
}

# Detect whether the binary argument exists and is non-empty. Sets a global
# BIN_VALID=ok|missing for callers.
assert_binary_present() {
  local binary="$1"
  if [[ -z "$binary" ]]; then
    BIN_VALID="missing"
    return 1
  fi
  if [[ ! -e "$binary" ]]; then
    BIN_VALID="missing"
    return 1
  fi
  BIN_VALID="ok"
  return 0
}

# Begin timing at module load; wrappers can override WRAPPER_START_MS if
# they want a different start point.
WRAPPER_START_MS="$(_now_ms)"
