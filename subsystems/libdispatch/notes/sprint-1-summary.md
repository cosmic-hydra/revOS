# libdispatch — Sprint 1 Summary

**Subsystem agent:** `libdispatch`
**Harness SHA at run start:** 564580e (no harness drift during sprint)
**Artifact under audit:** `/usr/lib/system/introspection/libdispatch.dylib`
**SHA-256:** `0c6e2167fc596046a5c927ee72ed6fead1097ea5c952de0ad8f947f9a05d3286`
**OSS mirror:** `https://github.com/apple-oss-distributions/libdispatch` @ `2361ffb78a76f7ee488cd052eb0bc5c767118bf9` (tag `libdispatch-1542.0.4`)
**Local cache:** `/Users/vaithianathan/revOS-work/cache/libdispatch` (shallow)
**Platform:** darwin 27.0.0 arm64 (universal Mach-O with arm64e + x86_64 slices)

## Records committed

**12 records** (1 pre-existing + 11 written this sprint), all passing
`scripts/lib/validate_evidence.py`:

| # | subject | claim_status | record file |
|---|---|---|---|
| 1 | `dispatch_queue_create` | observed | `evidence/dispatch_queue_create-0c6e.json` (pre-existing) |
| 2 | `dispatch_async` | observed | `evidence/dispatch_async-0c6e.json` |
| 3 | `dispatch_sync` | observed | `evidence/dispatch_sync-0c6e.json` |
| 4 | `dispatch_once` | observed | `evidence/dispatch_once-0c6e.json` |
| 5 | `dispatch_source_type_*` (count delta) | observed | `evidence/dispatch_source_type_data_add-0c6e.json` |
| 6 | `dispatch_semaphore_create` | observed | `evidence/dispatch_semaphore_create-0c6e.json` |
| 7 | `dispatch_group_create` | observed | `evidence/dispatch_group_create-0c6e.json` |
| 8 | `dispatch_group_enter` (pair) | observed | `evidence/dispatch_group_enter-0c6e.json` |
| 9 | `dispatch_after` | observed | `evidence/dispatch_after-0c6e.json` |
| 10 | `dispatch_io_create` | observed | `evidence/dispatch_io_create-0c6e.json` |
| 11 | `dispatch_main` (main_q delta) | observed | `evidence/dispatch_main-0c6e.json` |
| 12 | `dispatch_release` (ABSENT) | observed | `evidence/dispatch_release-0c6e.json` |

Honesty split: **11 observed + 1 explicit ABSENT** (record #12; the
GCD-to-ARC ownership migration). The two structural deltas
(`_dispatch_source_type_after` missing shipped, `__dispatch_main_q`
double-underscore Apple-private rename) are captured inside records #5
and #11 rather than as separate "deduced" records, because in both
cases the claim is grounded in a *direct* export-trie observation plus
an OSS cross-reference — not pure reasoning from one source alone.

## OSS-vs-shipped delta table

| symbol / shape | OSS (`2361ffb7`) | shipped (macOS 27 arm64e) | delta? | captured in record |
|---|---|---|---|---|
| count of `_dispatch_source_type_*` anchors | 20 | 19 (per arm64e slice) | YES, by 1 | #5 |
| `_dispatch_source_type_after` | present (source.c:1429) | absent from export trie | YES, OSS-only | #5 (via `dispatch_after` cross-ref also) |
| main queue struct anchor | `_dispatch_main_q` (init.c:259, single underscore) | `__dispatch_main_q` (double underscore, Apple-private) | YES, naming convention moved from public-spelly to Apple-private | #11 |
| `_dispatch_sync_recurse` (internal) | present (queue.c:1840) | absent from export trie (inlined/stripped) | YES, internal helper retired | #3 |
| public `dispatch_release` | defined (object.c:216) | absent from arm64e export trie | YES, GCD-to-ARC migration | #12 |

All five deltas point the same direction: **the shipped libdispatch is a
more conservative, more OS-private surface than the OSS mirror
suggests**, with public macros (`dispatch_release`) and internal
helpers (`_dispatch_sync_recurse`, `_dispatch_source_type_after`) all
retired in favor of underscored Apple-private replacements or pure
inlining. Tools and bindings that reach for the OSS spelling will
silently fail dlsym().

## Top 3 unknowns (carried into sprint 2)

1. **`_dispatch_mgr_q` static vs stripped status** — the manager queue
   anchor is also a candidate for the Apple-private double-underscore
   rename, but the symbol does not appear in the arm64e export trie at
   all (only in the x86_64 simulator slice does a partial match exist).
   Need to determine whether it is genuinely static-and-private or
   fully stripped, and whether downstream managers have moved to a
   MIG-port instead of a queue anchor.
2. **Exact set of `_dispatch_queue_attr_t` internal flags** —
   `dispatch_queue_attr_make_with_qos_class` and friends expose only a
   narrow cross-section of the OSS-internal flag bits (e.g.
   `DISPATCH_QUEUE_ATTR_INFIXED`, `DISPATCH_QUEUE_STRICT_TSR`). Need a
   diff between `dispatch/queue.h` enum names and the actual bit
   positions used in the shipped `_os_object_dispose` fast path.
3. **QOS class introspection** — `qos_class_self()`, `qos_class_main()`,
   and the `_dispatch_qos_class_from_string` mapping are not yet pinned
   to the shipped binary; we suspect an Apple-private
   `__qos_class_for_protocol_qos_table` indirection exists that is
   missing from OSS, and it changes how QOS policy affects queue
   ordering.

## Validation

```
$ python3 scripts/lib/validate_evidence.py .
validated 76 evidence records: 76 ok, 0 failing
```

(The 76 is the full repo, including the 12 libdispatch records plus
records owned by the other sprint-1 subsystems.)

## Reproducibility

Every record carries a `reproducer` field; the parent harness runs
those commands against the same `/usr/lib/system/introspection/libdispatch.dylib`
SHA-256 prefix `0c6e2167`. If that hash changes (a Security Update
bumps it), the records are stale and the next sprint must re-derive
from the new hash.
