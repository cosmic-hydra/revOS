# `cf-types` — CoreFoundation boxed-type and reference-counted ABI surface

**Sprint 1 owner:** cf-types agent
**Goal:** catalog the **public** CoreFoundation boxed-type symbols and runtime
type-system primitives so that any reimplementation or shim library can present
the same opaque handle ABI.

## Owned subtrees

This agent owns:

- `subsystems/cf-types/evidence/*.json` — every evidence record (one per symbol).
- `subsystems/cf-types/notes/*.md` — analyst notes; never cite a property here
  without a paired evidence JSON.
- `subsystems/cf-types/README.md` (this file).

This agent does **not** own anything else. Do not touch `subsystems/cf-runtime/`,
`subsystems/libdispatch/`, `subsystems/foundation-bridge/`, or
`subsystems/_meta/`.

## In-scope symbols (initial set; expand only with evidence-backed claims)

The boxed-type root and reference-counting primitives:

- `CFTypeRef` (the universal handle / `const struct __CFString *` style typedef).
- `CFTypeID`, `CFHashCode`, `CFTypeRef` callbacks:
  `CFRetain`, `CFRelease`, `CFRetainCount`, `CFEqual`, `CFHash`, `CFCopyDescription`,
  `CFGetTypeID`, `CFGetAllocator`, `CFSetAllocator`.
- Family constructors: `CFBooleanGetTypeID` and the kCFBoolean* constants.

Concrete boxed types (the type IDs and the canonical "GetTypeID" + at least one
free-form create call each):

- `CFStringRef` — `CFStringGetTypeID`, `CFStringCreateWithCString`,
  `CFStringGetCString`, `CFStringGetLength`, `CFStringGetCharacters`,
  `CFStringCompare`, `CFStringFind`, `CFStringCreateArrayBySeparatingStrings`,
  the `kCFCompare*` constants.
- `CFArrayRef` / `CFMutableArrayRef` — `CFArrayGetTypeID`,
  `CFArrayCreate`, `CFArrayGetCount`, `CFArrayGetValueAtIndex`,
  `CFArrayBSearchValues`, plus `kCFArray*` callbacks.
- `CFDictionaryRef` / `CFMutableDictionaryRef` — `CFDictionaryGetTypeID`,
  `CFDictionaryCreate`, `CFDictionaryGetCount`, `CFDictionaryGetValue`,
  `CFDictionaryContainsKey`, plus `kCFDictionary*` callbacks.
- `CFSetRef` / `CFMutableSetRef` — `CFSetGetTypeID`, `CFSetCreate`,
  `CFSetGetCount`, plus `kCFSet*` callbacks.
- `CFDataRef` / `CFMutableDataRef` — `CFDataGetTypeID`, `CFDataCreate`,
  `CFDataGetLength`, `CFDataGetBytePtr`, plus `kCFData*` callbacks.
- `CFNumberRef` / `CFMutableNumberRef` — `CFNumberGetTypeID`, `CFNumberCreate`,
  `CFNumberGetValue`, plus `kCFNumber*` type tags.
- `CFDateRef` / `CFAbsoluteTime` — `CFDateGetTypeID`, `CFDateCreate`,
  `CFDateGetAbsoluteTime`, `CFDateGetTimeIntervalSinceDate`,
  `CFDateCompare`, plus `kCFDate*` constants and the `CFCalendarRef`
  reference if the agent finds it exported by the same framework.
- `CFURLRef` / `CFMutableURLRef` — `CFURLGetTypeID`, `CFURLCreateWithString`,
  `CFURLCreateWithFileSystemPath`, `CFURLCopyFileSystemRepresentation`,
  plus `kCFURL*` keys for resource properties.
- `CFErrorRef` — `CFErrorGetTypeID`, `CFErrorCreate`, `CFErrorCopyDescription`,
  `CFErrorGetCode`, `CFErrorGetDomain`.
- `CFUUIDRef` — `CFUUIDGetTypeID`, `CFUUIDCreate`, `CFUUIDCreateString`,
  `CFUUIDCreateFromString`, `CFUUIDGetUUIDBytes`.

The agent SHOULD add more symbols only when a public API guarantee is
demonstrated by the evidence record.

## Source artifacts (canonical targets)

- `CoreFoundation.framework/Versions/A/CoreFoundation` on the host (path may
  vary per OS release; resolve with `xcrun --show-sdk-path -sdk macosx`).
- `Foundation.framework/Versions/C/Foundation` — for the toll-free-bridge
  confirmation cross-checks (owned together with foundation-bridge agent only
  via cross_reference, never by direct edit).

## Open-source mirror

Primary mirror: <https://github.com/apple-oss-distributions/CF> (the
`CF-Lite` subset Apple publishes). Cross-reference every claim against the
mirror and record the upstream URL in the `cross_reference` array.

Secondary mirrors when the primary lacks a symbol:

- <https://github.com/apple/swift-corelibs-foundation> (the Swift Foundation
  port; useful for behavior and exact type-id integers, NOT for Mach-O ABI).

## How to record evidence

1. Locate the symbol with `scripts/bin/nm-symbols --filter='^CF' <binary>`.
2. Cross-check with `scripts/bin/otool-exports <binary>` for the same symbol
   in the `-Iv` export list when present.
3. Write a `subsystems/cf-types/evidence/<symbol>.json` conforming to
   `evidence/schema.json` (top of repo).
4. Cite the *exact* wrapper invocation in `observation.tool_invocation`.
5. Cite the upstream URL in `cross_reference` for the open-source mirror.
6. Set `claim_status` honestly:
   - `observed` if the symbol appears in the public Mach-O export table.
   - `deduced` if behavior is reasoned from the opensource-apple mirror.
   - `unknown` if the agent cannot establish the symbol at all.

## Honesty contract (applies to every record)

- Never invent a name. If `nm-symbols` didn't return it, you cannot claim it.
- Never headline an Apple private framework export as public. Only the
  `<framework>/Versions/A/<framework>` re-exported surface is canonical.
- Never paste a proprietary blob into `observation.raw_output_excerpt`.

## Verifying locally

```bash
# 1. List known public CoreFoundation boxed-type symbols.
scripts/bin/nm-symbols \
  /System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation \
  --filter='^CF(GetTypeID|Retain|Release|Hash|Equal|CopyDescription)$' | jq .

# 2. Validate every evidence JSON this agent has produced.
python3 scripts/lib/validate_evidence.py
```
