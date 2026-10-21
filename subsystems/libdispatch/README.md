# `libdispatch` — GCD queue / source / sync primitives

**Sprint 1 owner:** libdispatch agent
**Goal:** catalog the **public** `libdispatch` ABI so that a free or
out-of-process reimplementation can match what client code links against. This
agent is the closest to a clean room situation because the opensource-apple
mirror is intentionally close in age and behavior to what Apple ships.

## Owned subtrees

- `subsystems/libdispatch/evidence/*.json`
- `subsystems/libdispatch/notes/*.md`
- `subsystems/libdispatch/README.md` (this file)

Do not edit `subsystems/cf-runtime/`, `subsystems/cf-types/`,
`subsystems/foundation-bridge/`, or `subsystems/_meta/`.

## In-scope symbols (initial set; expand only with evidence-backed claims)

Queue types and lifecycle:

- `dispatch_queue_t`, `dispatch_queue_attr_t`,
  `DISPATCH_QUEUE_SERIAL`, `DISPATCH_QUEUE_CONCURRENT`, `DISPATCH_QUEUE_SERIAL_INACTIVE`.
- `dispatch_queue_create`, `dispatch_queue_create_with_account`,
  `dispatch_queue_get_label`, `dispatch_get_global_queue`,
  `dispatch_get_main_queue`, `dispatch_queue_set_specific`,
  `dispatch_get_specific`, `dispatch_queue_reset`,
  `dispatch_queue_set_event_handler`,
  `dispatch_barrier_async`, `dispatch_barrier_sync`,
  `dispatch_barrier_async_f`.

Sync / async:

- `dispatch_async`, `dispatch_async_f`,
  `dispatch_sync`, `dispatch_sync_f`,
  `dispatch_once`, `dispatch_once_t`,
  `dispatch_after`, `dispatch_after_f`,
  `dispatch_apply`, `dispatch_apply_f`,
  `dispatch_get_context`, `dispatch_set_context`.

Group:

- `dispatch_group_t`, `dispatch_group_create`, `dispatch_group_async`,
  `dispatch_group_wait`, `dispatch_group_notify`,
  `dispatch_group_enter`, `dispatch_group_leave`.

Semaphore:

- `dispatch_semaphore_t`, `dispatch_semaphore_create`,
  `dispatch_semaphore_wait`, `dispatch_semaphore_signal`,
  `dispatch_semaphore_wait_timeout`.

Source / IO:

- `dispatch_source_t`, `dispatch_source_create`,
  the `DISPATCH_SOURCE_TYPE_*` constants (`DATA_ADD`, `DATA_OR`, `PROC`, `TIMER`,
  `VNODE`, `WRITE`, `READ`, `SIGNAL`, `MEMORYPRESSURE`).
- `dispatch_source_set_event_handler`, `dispatch_source_set_cancel_handler`,
  `dispatch_source_cancel`, `dispatch_source_testcancel`,
  `dispatch_source_get_data`, `dispatch_source_get_handle`,
  `dispatch_source_get_mask`.
- `dispatch_io_t`, `dispatch_io_create`,
  `dispatch_io_read`, `dispatch_io_write`, `dispatch_io_set_high_water`,
  `dispatch_io_set_low_water`, `dispatch_io_barrier`.

Object lifecycle:

- `dispatch_retain`, `dispatch_release`,
  `dispatch_object_t` (and the `DISPATCH_OBJECT_*` constants),
  `dispatch_resume`, `dispatch_suspend`.

Memory:

- `dispatch_data_t`, `dispatch_data_create`,
  `dispatch_data_get_size`, `dispatch_data_create_map`,
  `dispatch_data_create_subrange`, `dispatch_data_apply`.

Time:

- `dispatch_time_t`, `dispatch_time`, `dispatch_walltime`.

Qos / attr:

- the `QOS_CLASS_*` constants and `dispatch_get_global_queue(..., QOS_CLASS_*)`.

## Source artifacts (canonical targets)

- `usr/lib/system/libdispatch.dylib` (the on-host dylib).
- `/usr/lib/system/libxpc.dylib` and `libsystem_kernel.dylib` — record only the
  negative observations explicitly so readers know we did *not* find libdispatch
  symbols there.

## Open-source mirror

Primary mirror: <https://github.com/apple-oss-distributions/libdispatch>.

This is the most complete mirror in the repo. Every claim should cite the
mirror's path and revision (use `git log --pretty=format:%H -- <path>`). For
behaviour questions (e.g. queue ordering, QOS class transitions), also
reference <https://github.com/apple/swift-corelibs-dispatch>.

## How to record evidence

1. `scripts/bin/nm-symbols --filter='^_' /usr/lib/system/libdispatch.dylib` —
   lots of `_dispatch_*` symbols.
2. `scripts/bin/strings-grep --pattern='DISPATCH_' /usr/lib/system/libdispatch.dylib`
   to discover exported flag constants.
3. Write `subsystems/libdispatch/evidence/<symbol>.json` conforming to
   `evidence/schema.json`.
4. In `cross_reference`, add:
   - `upstream: opensource-apple/libdispatch`
   - `url: <mirror's path after libdispatch-main>/<file>.c#L<line>`
   - `label` naming the upstream symbol/macro.

## Honesty contract

- libdispatch has had many renames (e.g. `_dispatch_object_activate`). Record
  the **shipped** symbol; note historical names in `notes/` only with their
  own evidence record.
- Never paste the upstream `*Private.h` API into a record. Public headers
  (`dispatch/*.h`) only.
- If you have not verified a symbol against the Mach-O export table *or* the
  public header, the answer is `unknown`.

## Verifying locally

```bash
scripts/bin/nm-symbols /usr/lib/system/libdispatch.dylib --filter='^_dispatch_queue_create$'
scripts/bin/strings-grep --pattern='DISPATCH_QUEUE_SERIAL ' /usr/lib/system/libdispatch.dylib
python3 scripts/lib/validate_evidence.py
```
