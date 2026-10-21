# `foundation-bridge` — Foundation ↔ CoreFoundation / ObjC / Swift boundary

**Sprint 1 owner:** foundation-bridge agent
**Goal:** catalog the **public** Foundation ABI surface and the *toll-free
bridge* between `NSString` ↔ `CFString`, `NSArray` ↔ `CFArray`, etc., plus the
run-loop and KVC/KVO contracts. This is the only agent that owns private
crossings between subsystems; coordinate via `cross_reference` not by editing
the peer subsystem's evidence JSONs.

## Owned subtrees

- `subsystems/foundation-bridge/evidence/*.json`
- `subsystems/foundation-bridge/notes/*.md`
- `subsystems/foundation-bridge/README.md` (this file)

Do not edit `subsystems/cf-runtime/`, `subsystems/cf-types/`,
`subsystems/libdispatch/`, or `subsystems/_meta/`.

## In-scope symbols (initial set; expand only with evidence-backed claims)

Foundation base:

- `NSObject` class + key protocol conformance (the `NSObject` symbol itself
  plus the `+alloc / +new / +initialize / -dealloc / -isKindOfClass: /
  -respondsToSelector: / +class / -retain / -release / -autorelease /
  -description` family).
- The `isa` swizzling primitive `object_setClass`, `object_getClass`,
  `object_isClass`, `class_isSubclass`, and the runtime objects lookup
  `objc_getClass`, `objc_lookUpClass`, `objc_getProtocol`.

KVC / KVO:

- `NSKeyValueObservingProtocol`'s `+automaticallyNotifiesObserversForKey:` and
  the `-addObserver:forKeyPath:options:context:` family on `NSObject`.
- `valueForKey:`, `setValue:forKey:`, `mutableArrayValueForKey:`,
  `dictionaryWithValuesForKeys:`, `setValuesForKeysWithDictionary:`.
- The private-by-design `NSKVONotify_*` swizzling trampoline family — record
  these as `unknown` or `deduced`, never as `observed`, unless you can show a
  public symbol export for them.

Bridge to CoreFoundation (toll-free):

- `TollFreeBridging.h` accessor functions:
  `CFCastingBridgeToObjC`, `CFBooleanGetObjCValue`,
  the `CF_TO_OBJC` / `OBJC_TO_CF` macros in `<CoreFoundation/CFTree.h>` etc.
- `CFStringRef ↔ NSString *` (`-bridge` cast, identity-preserving).
- `CFArrayRef ↔ NSArray *`, `CFSetRef ↔ NSSet *`,
  `CFDictionaryRef ↔ NSDictionary *`, `CFDataRef ↔ NSData *`,
  `CFDate ↔ NSDate`, `CFURL ↔ NSURL`, `CFError ↔ NSError`.

Autorelease:

- `NSAutoreleasePool`, the runtime hooks `objc_autoreleasePoolPush` /
  `objc_autoreleasePoolPop`, plus the inline `__autorelease` ivar wiring.

Codable / archiving:

- `NSCoder`, `NSKeyedArchiver`, `NSKeyedUnarchiver`,
  `+archivedDataWithRootObject:requiringSecureCoding:error:`,
  `NSKeyedArchiverDelegate`,
  the `NSSecureCoding` protocol.

Run-loop bridge:

- `-run`, `-runUntilDate:`, `-runMode:beforeDate:` on `NSRunLoop`, the
  `+currentRunLoop`, `+mainRunLoop` factory methods, the `+scheduledTimerWith…`
  family, the `+perform…` selector family, and the `NSMachPort` /
  `NSMessagePort` symmetry with `CFSocket`/`CFRunLoopSource`.

Notification bridge:

- `NSNotification`, `NSNotificationCenter`, the `_didReceiveNotification:` shim
  that forwards into `CFNotificationCenterPostNotification` (record as
  `deduced` unless you can show a public symbol).

## Source artifacts (canonical targets)

- `/System/Library/Frameworks/Foundation.framework/Versions/C/Foundation` —
  the public re-exported surface.
- `/usr/lib/libobjc.A.dylib` for the Objective-C runtime surface.
- `/usr/lib/system/libdispatch.dylib` only when `Foundation.framework` re-exports
  a dispatch symbol (record the negative observation in this agent's notes).

## Open-source mirror

Primary mirrors:

- <https://github.com/apple-oss-distributions/objc4> — Objective-C runtime.
- <https://github.com/apple/swift-corelibs-foundation> — NSObject / NSString /
  NSArray / NSDictionary behavior (NOT for Mach-O ABI).
- <https://github.com/apple/swift-corelibs-xctest> for testing harness symbols
  only.

## How to record evidence

1. Use `scripts/bin/class-dump-types` against the
   `Foundation.framework/Versions/C/Foundation` Mach-O. Note the harness
   treats a missing `class-dump` binary as `tool-not-installed`, not as
   `tool-failed` — fall back to `nm-symbols` in that case.
2. For toll-free bridge symbols, consult
   <https://github.com/apple-oss-distributions/objc4> `runtime/Foundation.h`
   or the swift-corelibs-foundation `_NSObjectSwift.swift` mirror.
3. Record everything in `subsystems/foundation-bridge/evidence/*.json`.

## Honesty contract

- Toll-free bridge identity is an ABI promise, not a guess. If you cannot
  show the symbol is **shipped** by the host, mark `unknown` and stop.
- Private KVO swizzling has zero public symbol exports on most macOS releases;
  do not pretend otherwise.
- If `class-dump-types` is not installed, document the install hint and rely
  on `nm-symbols` plus header diffs — never on memory.

## Verifying locally

```bash
scripts/bin/class-dump-types /System/Library/Frameworks/Foundation.framework/Versions/C/Foundation | jq .
scripts/bin/nm-symbols \
  /System/Library/Frameworks/Foundation.framework/Versions/C/Foundation \
  --filter='^_NS' | jq .

python3 scripts/lib/validate_evidence.py
```
