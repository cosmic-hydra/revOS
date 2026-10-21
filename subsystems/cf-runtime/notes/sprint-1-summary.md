# cf-runtime — Sprint 1 summary

Scope: the run-loop / event / plug-in ABI surface of CoreFoundation
(`CFRunLoop*`, `CFNotificationCenter*`, `CFSocket*`, `CFStream*`, `CFPlugIn*`).

26 evidence records, all conforming to `evidence/schema.json`.
21 `observed` @ 0.9, 3 `deduced` @ 0.5, 2 `unknown` @ 0.0 (see *Unknowns*).

---

## 1. The finding that shapes this whole sprint

**CoreFoundation has no standalone Mach-O on macOS 27.** This is not a
tooling bug — it is how the OS ships the framework:

```
$ realpath /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation
/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation: No such file or directory
```

The framework directory contains only `Resources/` and `_CodeSignature/`. The
`CoreFoundation` symlink is **broken**; `dyld_shared_cache_arm64e.map` lists the
real image path
`/System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation`
with no on-disk file behind it. The image lives in the arm64e dyld shared cache.

Consequence for the harness: **the prescribed wrappers cannot see it.**

| Wrapper | Target | Result |
|---|---|---|
| `scripts/bin/nm-symbols` | CoreFoundation | `{"tool":"nm","status":"tool-failed","exit_code":1}` |
| `scripts/bin/otool-exports` | CoreFoundation | `{"tool":"otool","status":"tool-failed","exit_code":1}` |
| `scripts/bin/nm-symbols` | `libsystem_pthread.dylib` (control) | `{"tool":"nm","status":"ok","total":139}` |

The control row matters: the wrappers are **not** broken, they degrade gracefully
(`status: tool-failed`, clean JSON, non-zero exit) — the artifact is simply not a
file. `nm` cannot read the cache either
(`The file was not recognized as a valid object file`), because a shared cache is a
custom container, not a Mach-O.

`class-dump` is absent and **has no Homebrew formula** (only Objective-C classes
are in scope here anyway — CF's run-loop surface is C).

### Tool substitution, stated plainly

CoreFoundation export-table evidence in this subtree was gathered with:

```
dyld_info -exports /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation
```

`dyld_info` resolves the canonical framework path through the shared cache and
reads the image's `LC_DYLD_EXPORTS_TRIE` — the same export table `otool-exports`
and `nm-symbols` would have read had the file existed. Records therefore carry
`observation.tool: "other"` with the verbatim invocation, per AGENTS.md
*"Cite the tool that observed the symbol"*. **No record claims to have used
`nm-symbols` or `otool-exports` for CoreFoundation.**

`source_artifact` is the verbatim `dyld_info -exports` dump captured to
`cache/cf-runtime/cf-exports-corefoundation.txt` (sha256 `55c58b30c63b…`) — the
artifact that was actually observed, so the hash pins the exact evidence rather
than a multi-gigabyte container. The cache it came from is identified by its own
sha256 in each record's `observation.summary`.

Incidentally, `cf-types` independently captured the same table and its
`cf-exports-arm64e.txt` hashes to the **same** `55c58b30c63b…`. Two agents, one
deterministic dump — the export table is stable across runs, which is what makes
these records re-derivable.

**For the Curator / other subsystem agents:** `cf-types` will hit this identical
wall for CFString/CFArray work. A `dyld-info-exports` wrapper emitting the same
`output-schema.json` envelope would unblock the whole lane.

## 2. What the export table shows

55 `CFRunLoop*` symbols are exported. Records cover the briefed priority areas.

**Run-loop lifecycle.** `CFRunLoopGetCurrent`, `CFRunLoopRun`,
`CFRunLoopRunInMode`, `CFRunLoopStop` all present as `__TEXT` function symbols.

**Mode constants are data, not functions.** `kCFRunLoopDefaultMode` (0x5FCB89F8)
and `kCFRunLoopCommonModes` (0x5FCB8A00) are exported *data* symbols. Segment
spans read from the cache map place both in `__DATA_CONST`
(0x1E020DB38–0x1E05BF938), and the two are **exactly 8 bytes apart** — one 64-bit
pointer on arm64. Adjacent `CFStringRef` globals, matching their
`const CFStringRef` declaration upstream. This is the kind of detail a plain
grep-for-the-symbol would miss.

**Observers / sources / timers.** `CFRunLoopAddObserver`,
`CFRunLoopObserverDoesRepeat`, `CFRunLoopAddSource`, `CFRunLoopSourceSignal`,
`CFRunLoopAddTimer`, `CFRunLoopTimerSetNextFireDate`, `CFRunLoopTimerInvalidate`
— all present.

**Notification centres.** Three distinct accessors exist: local, distributed, and
`CFNotificationCenterGetDarwinNotifyCenter`. Cross-checked against
`libsystem_notify.dylib`: its export trie carries `notify_post` and
`notify_register_check` but **not** `notify_new`. The Darwin notify centre is
built on the check-and-register token API. (Record:
`notification-center-vs-darwin-notify`.)

**Sockets / streams / plug-ins.** `CFSocketCreate`,
`CFSocketConnectToAddress`, `CFSocketCreateRunLoopSource`; `CFSocketCreateRunLoopSource`
and `CFReadStreamScheduleWithRunLoop` are the explicit run-loop bridges.
`CFStreamCreatePairWithSocketToHost`, `CFReadStreamGetTypeID`,
`CFWriteStreamGetTypeID`, `CFReadStreamScheduleWithRunLoop`. Plug-in ABI:
`CFPlugInInstanceCreate`, `CFPlugInInstanceGetInterfaceFunctionTable`.

## 3. Corrections to the sprint brief

Two briefed subjects **do not exist** as named. Recorded as `deduced`, not
`observed`, per AGENTS.md rule 5:

- **`CFRunLoopGetCommonMode` / `CFRunLoopGetCommonModes`** — absent from the macOS
  27 export table *and* absent from the 2015 `apple-oss-distributions/CF` mirror,
  whose `CFRunLoop.h` declares `CFRunLoopCopyAllModes` / `CFRunLoopCopyCurrentMode`
  instead. The mirror has no `GetCommonMode` at all. The `Copy*` pair is exported.
- **`CFReadStreamRef` / `CFWriteStreamRef`** — these are typedefs, so they emit no
  symbol; recording them as `observed` would have been fabrication. Their
  accessors (`CFReadStreamGetTypeID`, `CFWriteStreamGetTypeID`) are recorded
  instead.

Also absent: `CFRunLoopRunUntilDate` and a generic `CFStreamGetTypeID`.

## 4. Unknowns

Kept at `unknown` / `0.0` rather than guessed:

1. **Run-loop internals.** We have the export table only. How `CFRunLoopRunInMode`
   multiplexes sources, timers and observers, and its `mach_msg` integration, is
   entirely unobserved. Needs disassembly of `__TEXT` (a future harness with a
   disassembler) — no Hopper/Ghidra per sprint constraints.
2. **File-descriptor source behaviour.** The brief flagged this as subtle. It is
   `CFRunLoopSourceCreate` with a `version 0` `CFRunLoopSourceContext` using
   `kCFRunLoopSourceCallBacks`, and the fd-signalled (`DISPATCH_SOURCE_TYPE_VNODE`
   / `EVFILT_VNODE`) path is *not* observable from exports. Not closable this sprint.
3. **Semantics of `kCFRunLoopCommonModes`.** That the symbol is a global pointer
   is observed; that it is a *pseudo-mode* string the run loop treats as a set is
   upstream-documentation inference, not an export-table fact.

Cross-subystem note for `libdispatch`: `CFReadStreamSetDispatchQueue` /
`CFWriteStreamSetDispatchQueue` and `notify_register_dispatch` are both exported,
confirming CoreFoundation has a libdispatch-backed path distinct from the run-loop
one. Not claimed here — that lane is `libdispatch`'s to record.

## 5. Provenance

- Observed artifact: `cache/cf-runtime/cf-exports-corefoundation.txt`
  sha256 `55c58b30c63b3a31b3a150a27db1fd09cbac51269ae4918d9f9940de730dea95`
  (verbatim `dyld_info -exports` dump of CoreFoundation's export trie)
- notify artifact: `cache/cf-runtime/notify-exports.txt`
  sha256 `a9629368bd08d2c82abec66d8c1a9517a082c0960123f6111e39af535e30ed9b`
- Source cache: `/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld/dyld_shared_cache_arm64e`
  sha256 `ecc822c56dbce82d0f151afd7bf8492e91b109944483614f0eaaf377ac7d21da`
- Platform: macOS 27.0 (26A5388g), arm64e
- Mirror: `https://github.com/apple-oss-distributions/CF` @ `dc54c6b` (2015-06-23),
  cloned to `/Users/vaithianathan/revOS-work/cache/CF` (not committed)