# `cf-runtime` — CoreFoundation run-loop, notification, socket, plug-in, stream

**Sprint 1 owner:** cf-runtime agent
**Goal:** catalog the **public** CoreFoundation runtime (run loop + observers,
notification center, sockets, plug-ins, streams) so that any reimplementation
or shim library can present the same opaque-handle ABI used by Foundation and
third-party code.

## Owned subtrees

- `subsystems/cf-runtime/evidence/*.json`
- `subsystems/cf-runtime/notes/*.md`
- `subsystems/cf-runtime/README.md` (this file)

Cross-boundary symbols (e.g. `CFRunLoop` ↔ `NSRunLoop`) are owned **here** for
the CoreFoundation side and by foundation-bridge for the NS side. The two
agents coordinate via cross_reference URL entries, not by editing each other's
files.

## In-scope symbols (initial set; expand only with evidence-backed claims)

Run loop:

- `CFRunLoopRef`, `CFRunLoopMode`, `CFStringRef`-keyed mode names
  (`kCFRunLoopDefaultMode`, `kCFRunLoopCommonModes`, plus every
  `kCFRunLoop*Mode` exported by the framework).
- Lifecycle: `CFRunLoopGetCurrent`, `CFRunLoopGetMain`,
  `CFRunLoopRun`, `CFRunLoopRunInMode`, `CFRunLoopWakeUp`,
  `CFRunLoopStop`, `CFRunLoopContainsObserver`, `CFRunLoopAddObserver`,
  `CFRunLoopAddSource`, `CFRunLoopAddTimer`, `CFRunLoopRemove*`.

Run-loop sources / timers / observers:

- `CFRunLoopSourceRef`, `CFRunLoopSourceContext`,
  `CFRunLoopSourceCreate`, `CFRunLoopSourceSignal`,
  `CFRunLoopSourceInvalidate`.
- `CFRunLoopTimerRef`, `CFRunLoopTimerContext`,
  `CFRunLoopTimerCreate`, `CFRunLoopTimerSetNextFireDate`,
  `CFRunLoopTimerGetNextFireDate`, `CFRunLoopTimerInvalidate`.
- `CFRunLoopObserverRef`, `CFRunLoopObserverContext`,
  `CFRunLoopObserverCreate`, `CFRunLoopObserverGetActivities`,
  the `kCFRunLoopEntry / kCFRunLoopBeforeTimers / …` activity constants.

Notification:

- `CFNotificationCenterRef`, `CFNotificationName`, `CFNotificationCallback`.
- `CFNotificationCenterGetLocalCenter`, `CFNotificationCenterGetDarwinNotifyCenter`.
- `CFNotificationCenterAddObserver`, `CFNotificationCenterPostNotification`,
  `CFNotificationCenterRemoveObserver`, `CFNotificationCenterRemoveEveryObserver`.

Socket:

- `CFSocketRef`, `CFSocketContext`, the `kCFSocket*` flags (`kCFSocketReadCallBack`,
  `kCFSocketAcceptCallBack`, etc.).
- `CFSocketCreate`, `CFSocketCreateWithNative`, `CFSocketGetNative`,
  `CFSocketSendData`, `CFSocketConnectToAddress`, `CFSocketSetDelegate`,
  `CFSocketGetContext`, `CFSocketInvalidate`, `CFSocketRelease`,
  plus the run-loop integration helpers `CFSocketCreateRunLoopSource`,
  `CFSocketGetTypeID`.

Plug-in / bundle:

- `CFPlugInRef`, `CFPlugInInstanceRef`, `CFPlugInFactoryFunction`.
- `CFPlugInCreate`, `CFPlugInGetTypeID`,
  `CFPlugInRegisterFactoryFunction` / `CFPlugInUnregisterFactoryFunction`,
  `CFPlugInFindFactoriesForPlugInType`, `CFPlugInCreateInstance`.

Stream:

- `CFReadStreamRef`, `CFWriteStreamRef`,
  `CFStreamCreatePairWithSocketToHost`, `CFStreamCreatePairWithFileDescriptor`,
  the `kCFStream*` event constants and the `CFStreamClientContext`
  + `CFStreamScheduleWithRunLoop` / `CFStreamOpen` / `CFStreamClose` /
  `CFStreamRead` / `CFStreamWrite` family.

Network (`CFNetwork` is out of scope for sprint 1 — see ROADMAP).

## Source artifacts (canonical targets)

- `CoreFoundation.framework/Versions/A/CoreFoundation` on the host.
- `CFNetwork.framework/Versions/A/CFNetwork` only if you need to record a
  negative observation ("symbol not in `CoreFoundation`; expected to live in
  `CFNetwork`").

## Open-source mirror

Primary mirror: <https://github.com/apple-oss-distributions/CF> (CF-Lite).

For socket / stream claims, also reference:

- <https://github.com/apple/swift-corelibs-foundation> — for `URLSession` /
  `Network.NSStream` re-implementation behavior (NOT for the Mach-O ABI).

## How to record evidence

1. Locate the symbol with `scripts/bin/nm-symbols --filter='^CFRunLoop' <binary>`.
2. Cross-check with `scripts/bin/otool-exports <binary>`.
3. Write `subsystems/cf-runtime/evidence/<symbol>.json` conforming to
   `evidence/schema.json`.
4. Record the upstream URL in `cross_reference` for the opensource-apple mirror.

## Honesty contract

- Do not speculate about internal threading models. If you observe a symbol,
  record it as `observed`. If you reason from the opensource-apple mirror,
  record it as `deduced`. Anything else is `unknown`.
- Do not lift names from the macOS `header files` (e.g. `CFRunLoop.h`) without
  *also* producing an evidence record. Headers name what is intended; binaries
  name what is shipped.

## Verifying locally

```bash
scripts/bin/nm-symbols \
  /System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation \
  --filter='^CFRunLoop' | jq .

python3 scripts/lib/validate_evidence.py
```
