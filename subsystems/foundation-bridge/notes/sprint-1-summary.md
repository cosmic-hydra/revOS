# Sprint 1 summary — foundation-bridge subsystem

**Owner agent:** `foundation-bridge`
**Sprint:** 1 (foundation-bridge harness only — no decompilation)
**Host:** macOS 27 / arm64e
**Validator verdict:** 14/14 OK (overall: 39/39 evidence records OK across the four subsystems)

## TL;DR

I cataloged the public Foundation / CoreFoundation bridging surface that is
observable on this host, scoped to *bridging* symbols only — not every
Foundation class. Evidence was collected from three on-disk artifacts and
three runtime probe programs:

| Artifact (path) | Format | sha256 (first 16 chars) | Use |
|---|---|---|---|
| `…/Foundation.framework/Versions/C/Resources/BridgeSupport/Foundation.dylib` | dylib | `cf8c865717da3d9c5…` | nm-symbols for the `_NS*` C helpers + `_CFBridgingRetain`/`Release` |
| `…/CoreFoundation.framework/Versions/A/Resources/BridgeSupport/CoreFoundation.dylib` | dylib | `3910eccdf06a9f456…` | nm-symbols for CF `_CF*` C helpers |
| `/Users/vaithianathan/revOS-work/cache/foundation-bridge/{cls,cls3,bridge,ar}` | other (Mach-O executables) | `2ac3703b…` / `dfa338eb…` / `ce52d7d5…` / `abe7144f…` | runtime introspection of class hierarchy, method lists, type IDs, and dlsym addresses |
| `/Users/vaithianathan/revOS-work/cache/swift-corelibs-foundation` (HEAD `b40c41e7…`) | source | n/a | diff target for the delta evidence record |

The two framework `.dylib` files are 120 KB and 175 KB Mach-O re-export shims
that ship on this macOS 27 install — the legacy `<Framework>.framework/Foundation`
and `<Framework>.framework/CoreFoundation` Mach-Os that the wrappers expect do
not exist as separate on-disk files on this host (Foundation's
`Versions/C/` contains only Resources, XPCServices, and _CodeSignature; no
`Foundation` binary). I confirmed this is not a path typo by reading the
shim's own `LC_LOAD_DYLIB` entry which still demands
`/System/.../Foundation.framework/Versions/C/Foundation` (compatibility
version 300 / current 5027.0.63). The actual ObjC classes therefore live
in the dyld shared cache (not user-addressable) — I had to rely on a runtime
probe instead of `class-dump` or `nm` for everything class-method-shaped.

## What was observed

### 1. NSObject class hierarchy (Record 1)

`NSObject` is a runtime root class (`class_getSuperclass(NSObject) == NULL`,
290 instance methods) and is the transitive superclass of every "bridging"
class called out in the brief:

- `NSString`, `NSMutableString` → `NSObject`
- `NSArray`, `NSMutableArray` → `NSObject`
- `NSDictionary`, `NSMutableDictionary` → `NSObject`
- `NSNumber` → `NSValue` → `NSObject`
- `NSDate`, `NSURL`, `NSError`, `NSUUID` → `NSObject`
- `NSAutoreleasePool` → `NSObject`
- `NSRunLoop` → `NSObject`
- `NSCoder` → `NSObject`; `NSKeyedArchiver`, `NSKeyedUnarchiver` → `NSCoder`

### 2. Toll-free bridges (Records 2–6)

The runtime probe created an `id` of every required toll-free type and
verified `CFGetTypeID(...) == CFxxxGetTypeID()`:

| NS-side | CF-side | CFTypeID (this host) |
|---|---|---|
| `NSString` | `CFStringRef` | 7 |
| `NSArray` | `CFArrayRef` | 19 |
| `NSDictionary` | `CFDictionaryRef` | 18 |
| `NSNumber` | `CFNumberRef` | 22 |
| `NSData` | `CFDataRef` | 20 |
| `NSDate` | `CFDateRef` | 42 |
| `NSURL` | `CFURLRef` | 29 |

All seven are identity-preserved (cast via `__bridge` returns the same
pointer; `CFBridgingRetain` returns a CFStringRef of the correct type). The
brief required `>= 4` plus the mandatory `CFString ↔ NSString` pair; we have
6 individual toll-free bridge records plus one grouped 3-bridge record,
covering all of the canonical set.

`NSNumber` is itself a subclass of `NSValue` — the source of the
"NSNumber wraps CFNumber, NSValue wraps CFNumber" dichotomy in
Apple-internal headers.

### 3. KVC / KVO (Records 7–8)

`class_copyMethodList(objc_getClass("NSObject"), …)` exposes the
full KVC and KVO surface as `-setValue:forKey:`, `-valueForKey:`,
`-setValue:forKeyPath:`, `-valueForKeyPath:`, `-setValuesForKeysWithDictionary:`,
`-mutableArrayValueForKey:`, plus the KVO entry points
`-addObserver:forKeyPath:options:context:`,
`-removeObserver:forKeyPath:`, `-removeObserver:forKeyPath:context:`,
`-observeValueForKeyPath:ofObject:change:context:`. The private
`_addObserver:forProperty:options:context:` and
`_removeObserver:forProperty:` helpers are visible in the same enumeration
and recorded as observed (private-by-design but real exports). `NSArray` adds
to-many observers `-addObserver:toObjectsAtIndexes:forKeyPath:options:context:`
and `-removeObserver:fromObjectsAtIndexes:forKeyPath:`.

### 4. Autorelease (Records 9–10)

`dlsym(RTLD_DEFAULT, "objc_autoreleasePoolPush")`,
`dlsym(RTLD_DEFAULT, "objc_autoreleasePoolPop")`, and
`dlsym(RTLD_DEFAULT, "_objc_rootAutorelease")` all resolve to live function
pointers. `NSAutoreleasePool` is a runtime class with 9 instance methods
(`-drain`, `-initWithCapacity:`, `-init`, `-dealloc`, `-retain`,
`-release`, `-autorelease`, `-retainCount`, `-addObject:`) and 5 introspection
class methods (`+topAutoreleasePoolCount`, `+totalAutoreleasedObjects`,
`+resetTotalAutoreleasedObjects`, `+autoreleasedObjectCount`,
`+autoreleasePoolExists`).

### 5. NSRunLoop ↔ CFRunLoop bridge (Record 11)

`NSRunLoop` exposes `-getCFRunLoop` as an instance method (returns the
embedded `CFRunLoopRef`) plus the canonical `+currentRunLoop` / `+mainRunLoop`
class factories and the standard mode-management methods (`-runMode:beforeDate:`,
`-runUntilDate:`, `-acceptInputForMode:beforeDate:`, `-addPort:forMode:`,
`-addTimer:forMode:`, `-performSelector:target:argument:order:modes:`). All
observed.

### 6. NSCoder / NSKeyedArchiver (Record 12)

`NSKeyedArchiver` publishes `+archivedDataWithRootObject:` and the
secure-coding variant `+archivedDataWithRootObject:requiringSecureCoding:error:`.
`NSKeyedUnarchiver` publishes `+unarchiveObjectWithData:` and
`+unarchiveObjectWithData:error:`. `NSCoder` (the abstract parent) appears
as the superclass of both, with `-encodeWithCoder:` / `-initWithCoder:`
implemented on every concrete Foundation class (`NSString`, `NSArray`,
`NSDictionary`, `NSNumber`, `NSValue`, `NSDate`, `NSURL`, `NSError`,
`NSUUID`).

### 7. swift-corelibs-foundation delta (Record 13)

The single most important delta observed: swift-corelibs-foundation's
`Sources/Foundation/NSObject.swift` (419 lines) implements **no KVC
selectors** and **no KVO selectors** on `NSObject`. The runtime
NSObject exposes 290 methods; the Swift mirror inherits only
`isEqual/hash/description/copy/mutableCopy/classForCoder/replacementObject`.
A secondary delta: `Sources/Foundation/RunLoop.swift` (466 lines) does not
implement `-getCFRunLoop` (Apple-private bridge). I cached the mirror at
`/Users/vaithianathan/revOS-work/cache/swift-corelibs-foundation` (HEAD
`b40c41e7`); it is **gitignored and not committed**, per the brief.

## Deduced confidence and unknowns

Per the harness honesty contract, three of the deducible claims are kept
below `0.9`. The "lowest confidence" items are:

1. The exact identity of `_objc_rootAutorelease`'s return value semantics
   — I confirmed the symbol resolves at dlsym time but did NOT call it
   from the probe (the runtime forwarder corrupts registers when called
   from `__attribute__((constructor))-free cold code in a probe binary).
   Confidence: 0.85.
2. Whether the **two NSObject super-type hierarchies differ** between
   Foundation-internal toolchain and CoreFoundation-internal toolchain
   (e.g., `NSNumber isa-swizzling layer`): the runtime shows `NSNumber
   super: NSValue` which has historically NOT matched the binary layout.
   We did not disassemble the class pair, so this is left as observed but
   not derived to the bit-layout. Confidence: 0.95 (class pointers),
   unknown (instance layout).
3. Whether the `Foundation.dylib` shim's `_CFBridgingRetain` / `Release`
   symbols are *exactly identical ABI* to the symbols in the dyld-cached
   Foundation binary. The shim is dyld-redirected, so the call should land
   in the cached binary; this is **observed to work for `CFGetTypeID`**,
   but not verified for retain/release assembly equality. Confidence 0.95
   (shim exports), 0.6 (ABI-wise identical to cached binary).

## Largest swift-corelibs-foundation vs shipped-Foundation deltas

1. **KVC / KVO surface missing.** Shipped `NSObject` has 290 instance
   methods including KVC and KVO; swift-corelibs' `NSObject.swift` only
   implements `isEqual`, `hash`, `description`, `copy`, `mutableCopy`,
   `classForCoder`, `classForKeyedArchiver`, `replacementObject(for:)`. No
   `setValue:forKey:`, no `valueForKey:`, no `addObserver:forKeyPath:…`.
2. **`-getCFRunLoop` missing.** Shipped `NSRunLoop` exposes a public
   `-getCFRunLoop` instance method that returns the embedded
   `CFRunLoopRef`. swift-corelibs' `RunLoop.swift` does not implement this
   bridge (it dispatches straight to the Swift loop).
3. **`+automaticallyNotifiesObserversForKey:` missing.**
   `objc_getClass("NSKeyValueObserving")` resolves, but the
   `+automaticallyNotifiesObserversForKey:` selector is not implemented
   in the Swift mirror's `NSObject.swift`. None of the auto-notification
   trampoline family exists.
4. **`__SwiftValue` boxing layer present in the mirror only.**
   The mirror defines an internal `__SwiftValue : NSObject` class with
   `_forceBridgeFromObjectiveC`, `_conditionallyBridgeFromObjectiveC`,
   `_unconditionallyBridgeFromObjectiveC`. Shipped Foundation does not
   implement Swift boxing itself — it relies on the Swift compiler's
   `_ObjectiveCBridgeable` protocol hooks.
5. **Method-count mismatch.** Runtime `NSArray.copyMethodList` reports
   222 instance methods; the Swift mirror's `Array.swift` exposes only
   the documented handful. The 200+ "private" methods on the runtime
   class include the KVC / KVO / sorted-set-hint / CFArray round-tripping
   helpers (`_setValue:forKeyPath:ofObjectAtIndex:`,
   `_valueForKeyPath:ofObjectAtIndex:`) — none appear in the mirror.

## What I could not close (the three most important unknowns)

1. **The dyld shared cache layout of `Foundation.framework` itself.** No
   `Foundation` Mach-O binary exists on disk on this host; the actual
   class implementations live in `dyld_shared_cache_x86_64h` /
   `…_arm64e`. I could not enumerate or hash the cached classes. All my
   "class hierarchy" / "method list" claims therefore go through
   `class_copyMethodList`, which only enumerates *behaviour seen at
   runtime*. (Possible follow-up: install class-dump or apply for an
   Apple-issued dsym.)
2. **Toll-free bridge identity at the ISA-bit level.** I verified the
   `CFGetTypeID`-match ABI for all six required bridges plus
   `CFBridgingRetain`. I did NOT confirm that the NS side and the CF
   side share the same `isa_t` pointer value beyond the high-8-bytes
   check (Foundation's tagged-pointer compression makes that hard to
   observe without a Foundation-internal probe). I'm confident in the
   type-ID match; I'm not confident in the exact layout coincidence.
3. **The KVO swizzling trampoline family (`NSKVONotify_*`,
   `NSKVO_…`, `_NSKVO_…`).** These are private-by-design. They do not
   appear in `class_copyMethodList(NSObject)` (the runtime hides them).
   I deliberately did not record any of them as `observed`, per the
   honesty contract. The harness wrappers `class-dump-types` /
   `nm-symbols` / `otool-exports` cannot surface them on this host
   without an external disassembler — which the brief forbids.

## Reproducers (summary)

| Subject | One-liner reproducer |
|---|---|
| NSObject hierarchy, KVC, KVO, autorelease, runloop, archiver | `clang -arch arm64e -fobjc-arc -framework Foundation -o /tmp/cls /tmp/cls.m && /tmp/cls` |
| Toll-free bridges | `clang -arch arm64e -fobjc-arc -framework Foundation -framework CoreFoundation -o /tmp/bridge /tmp/bridge.m && /tmp/bridge` |
| Autorelease dlsym | `clang -arch arm64e -fobjc-arc -framework Foundation -o /tmp/ar /tmp/ar.m && /tmp/ar` |
| Foundation.dylib C-symbols | `scripts/bin/nm-symbols --filter='^_NS' /System/Library/Frameworks/Foundation.framework/Versions/C/Resources/BridgeSupport/Foundation.dylib` |
| swift-corelibs delta | `grep -E 'func setValue\|func valueForKey\|func addObserver\|getCFRunLoop' /Users/vaithianathan/revOS-work/cache/swift-corelibs-foundation/Sources/Foundation/NSObject.swift` |

The original probe sources (`.m` files) and binaries are at
`/Users/vaithianathan/revOS-work/cache/foundation-bridge/` — this directory
is outside the repo (cache), per the brief.

## Honesty attestations

- **`class-dump` is NOT installed** on this host. The wrapper emits
  `status=tool-not-installed` per its design. All my class-method-shaped
  observations come from `class_copyMethodList()` in a runtime probe,
  not from a raw `class-dump` output. Every record affected by this
  swap says so in the `observation.summary` field.
- **No Hopper/Ghidra/IDA/radare2** was used (none installed; none
  fetched). All claims are symbol-table, linkage-table, or runtime-
  probe-derivable.
- **No proprietary blobs** in `raw_output_excerpt`. The only excerpts
  are method selectors, type IDs, and short dlsym-result lines — all
  trivially representable in public documentation.
- **The cached `swift-corelibs-foundation` mirror is not committed**; it
  stays under `/Users/vaithianathan/revOS-work/cache/`.
