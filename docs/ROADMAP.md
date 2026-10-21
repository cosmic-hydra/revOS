# Roadmap — revOS

This document tracks the system surfaces that the agent team will reverse-engineer
across sprints. Each sprint produces a single harness commit (Curator) plus
evidence-record commits from each subsystem agent. No analysis is committed
in this roadmap file — it is a planning artefact, not an evidence log.

## Sprint 1 (this commit: harness only)

Status: **complete** with this commit.

### Subsystem agents in this sprint

- `cf-types` — CoreFoundation boxed-type ABI.
- `cf-runtime` — CoreFoundation run-loop / notification / socket / plug-in /
  stream ABI.
- `libdispatch` — GCD queue / source / sync / group / semaphore / IO ABI.
- `foundation-bridge` — Foundation ↔ CoreFoundation / ObjC / Swift bridges.

Each agent will write evidence JSONs into its own subtree
(`subsystems/<area>/evidence/*.json`) and have nothing to commit until the
Curator has shipped this harness.

## Future subsystems (candidate list, no commitment to scheduling)

These are reverse-engineering targets the team is likely to pursue after
sprint 1, in approximate order of demand from re-implementation / shim
authors. No analysis is committed for any of them in this sprint.

- **xnu / Mach-O loader** — `dyld`, `dyld_shared_cache`, the Mach-O LC_*
  variant Apple uses that public LLVM documents incompletely. Useful to a
  free dyld.
- **XPC** — `xpc_connection_*`, `xpc_object_*`, the `libxpc.dylib` ABI.
  Often confused with libdispatch; the message-passing surface is its own.
- **launchd** — `launchctl` contract and the job-policy plist schema. Useful
  for shims of `org.nspawn`, `keepalive`, and `ProcessType=Background`.
- **AppKit UI** — `NSView`, `NSEvent`, layout engine. Specifically NOT
  aligned with the current agent roster because the surface is huge and the
  re-use case is narrower.
- **libobjc runtime** — `objc_msgSend`, the `_objc_msgSend_uncached`
  trampoline, tagged-pointer layout, `isa` swizzling trampolines. We list
  this because the `foundation-bridge` agent touches some objc symbols but
  does not own the runtime proper.

## Scheduling policy

- Each subsystem agent commits to its own subtree only — see
  `AGENTS.md` ownership map.
- A subsystem may add to `in-scope symbols` of its own README; it does NOT
  add to another subsystem's README.
- Cross-cutting concerns (Apple-blessed conventions) belong in
  `AGENTS.md`, not in any one subsystem README.
- The CI gates run on every PR; landing requires green CI on `main`.

## Anti-goals

We will not, in any sprint:

- Reverse engineer private Apple frameworks (`Apple80211`, `IOKit`, …).
- Publish proprietary byte ranges from closed-source Apple code.
- Help circumvent Apple's licensing / DMMA restrictions. The opensource-apple
  mirrors are referenced for ABI study only; redistribution must respect
  Apple's licenses for those mirrors.
