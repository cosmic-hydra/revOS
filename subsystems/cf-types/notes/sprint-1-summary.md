# `cf-types` — Sprint 1 summary

**Host:** macOS 27.0, build 26A5388g, arm64 (arm64e slice).
**Artifact:** `/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation`,
UUID `F4CE3D4A-29B8-3F98-A136-7089CEB27692`, 3098 exported symbols.
**Mirror:** `apple-oss-distributions/CF` at `dc54c6bb1c1e5e0b9486c1d26dd5bef110b20bf3`
(tag `CF-1153.18`), shallow-cloned to `revOS-work/cache/` and never committed.

Every property below is paired with an evidence JSON in
`../evidence/`. Where a sentence has no paired record it is explicitly
labelled as an assumption or a gap.

---

## 1. The blocking environment finding (drives everything else)

**On macOS 27, CoreFoundation ships as a stub bundle.** The path named as the
canonical target in this subsystem's README does not contain a Mach-O:

```
/System/Library/Frameworks/CoreFoundation.framework/Versions/A/
  -> Resources/ and _CodeSignature/ only; no CoreFoundation file
```

`CoreFoundation` is a **dangling symlink**. The real image is
dyld-shared-cache-backed, so `nm`, `otool` and `strings` all fail on it:

```
scripts/bin/nm-symbols    -> status=tool-failed "binary not found"
scripts/bin/otool-exports -> status=tool-failed "binary not found"
scripts/bin/strings-grep  -> status=tool-failed "binary not found"
```

All three wrappers return `tool-failed` with the message *binary not found*,
which is technically accurate (the symlink target is absent) but hides the
real reason. **A future agent could easily mistake this for "CF is gone".**

**Working alternative: `dyld_info`.** It resolves through the shared cache and
returns the genuine export trie:

```bash
dyld_info -exports /System/Library/Frameworks/CoreFoundation.framework/CoreFoundation
```

All `observed` records in this sprint were taken that way, with
`observation.tool = "other"` (the schema's `otool|nm|strings|class-dump|...`
enum has no `dyld_info` member — a gap the Curator may want to close).

### Second source: the SDK `.tbd`

`CoreFoundation.tbd` (sha256 `2e4666e4…`) is Apple's link-time export stub
and *does* exist on disk. It independently lists all three tagged-pointer
strings, so the two sources agree. It was used as corroboration only.

---

## 2. Observed (claim_status `observed`, confidence 0.9)

**Runtime root primitives** — `cfgettypeid.json`, `cfequal.json`,
`cfhash.json`, `cfretain.json`, `cfrelease.json`, `cfcopydescription.json`.
`CFGetTypeID` 0x00020CAC, `CFEqual` 0x00008564, `CFHash` 0x00007CD4,
`CFRetain` 0x0000400C, `CFRelease` 0x0000A258, `CFCopyDescription`
0x0003D160. Note the public retain-count entry point is **`CFGetRetainCount`**
(0x000A3FB4), not `CFRetainCount` — the README's shorthand name does not exist.

**Boxed types, each with its core accessors present in the trie:**
`cfstringgettypeid.json`, `cfarraygettypeid.json`, `cfdictionarygettypeid.json`,
`cfsetgettypeid.json`, `cfdatagettypeid.json`, `cfnumbergettypeid.json`,
`cfdategettypeid.json`, `cfurlgettypeid.json`, `cferrorgettypeid.json`,
`cfuuidgettypeid.json`.

**Constants:** `kcfbooleantrue.json` (`kCFBooleanTrue`/`kCFBooleanFalse` are
exported *data* symbols, plus internal `__kCFBooleanTrue`/`__kCFBooleanFalse`
aliases), `kcfnull.json` (`kCFNull` is exported, as is `__kCFNull`).

### The arm64 tagged-pointer result (`cfstringcreatetaggedpointerstring.json`)

This was the sprint's highest-value finding. The export trie contains exactly
three CF tagged-pointer string entry points:

```
0x0016E624  __CFStringCreateTaggedPointerString
0x0016B4A0  __CFStringCreateIndirectASCIITaggedPointerString
0x0016B6BC  __CFIndirectTaggedPointerStringGetContents
```

**The CF-Lite mirror at `dc54c6b` contains none of these names** — `grep -rl`
over the whole tree returns nothing. So the arm64 tagged-pointer fast path
postdates CF-1153.18 and the mirror cannot be used to reason about it.

What the export table **cannot** give us is the bit layout itself. The claim
therefore stops at "the machinery exists and is exported"; the actual tag-bit
assignment is not observable from a trie and is **not claimed** here.

---

## 3. Deduced (claim_status `deduced`)

**`CFTypeID` (`cftypeid.json`, 0.7).** `CFBase.h` declares it twice under
`#if defined(__LLP64__) && __LLP64__` — `unsigned long long` vs
`unsigned long`. A `clang -E` probe on this host prints `LLP64_NO`, and Darwin
is LP64, so the `unsigned long` (64-bit) branch is in effect. `CFHashCode`
matches. `CFTypeID` is a typedef, so it has no export of its own; marking it
`observed` would violate the contract's rule against reproducing header-only
claims as observed.

**`CFRuntimeBase` (`cfruntimebase.json`, 0.5).** Confirmed absent from the
export trie (0 of 3098), absent from `CoreFoundation.tbd` (0 symbols), and
absent from the SDK's public `Headers/`. It exists only in the mirror's
`CFRuntime.h` as `uintptr_t _cfisa; uint8_t _cfinfo[4]; #if __LP64__ uint32_t _rc;`
— 16 bytes on arm64. Confidence is held at 0.5 because the mirror is a
different vintage from the macOS 27 binary and the real layout could differ.

**`CFStringEncoding` (`cfstringencoding.json`, 0.7).** A compile-time enum in
the published `CFString.h` (MacRoman=0, Unicode/UTF16=0x0100, ASCII=0x0600,
UTF8=0x08000100, UTF32=0x0c000100). The export trie contains **zero**
`_kCFStringEncoding*` data symbols, so these are link-time constants only —
there is nothing to observe at runtime.

**`__kCFAllocatorSystemDefault` (`private-kcfallocatorsystemdefault.json`, 0.7).**
This is a **negative** result worth recording. The briefing listed
`__kCFAllocatorSystemDefault` as an in-scope subject, but it is **not** an
exported symbol: 0 rows in the trie. The reason is visible in the mirror —
`CFBase.c` declares it `static struct __CFAllocator __kCFAllocatorSystemDefault`,
i.e. internal linkage. The *public* `kCFAllocatorSystemDefault` (0x5F940D88)
and `kCFAllocatorDefault` (0x00222C00) are exported; the double-underscore
backing object is not part of the linkable ABI.

---

## 4. Unknowns I could not close

1. **The tagged-pointer bit layout.** Three exported entry points prove the
   fast path exists; nothing in a trie or `.tbd` reveals which bits are stolen
   or the maximum inline length. Closing this needs a disassembly view of
   `__CFStringCreateTaggedPointerString` (offset 0x0016E624 in the cache
   image) — out of reach without Hopper/Ghidra, which are out of scope.
   This is the single most important open item for anyone reproducing CFString.
2. **`CFRuntimeBase`'s real layout on macOS 27.** Only the CF-1153.18 mirror
   describes it, and that mirror demonstrably lags the binary (see the tagged
   pointer gap). Whether `_cfisa`/`_cfinfo`/`_rc` still hold on arm64e is
   unverified. Needs a disassembly of `CFGetTypeID` or a `CFSTR()` at runtime.
3. **Numeric `CFTypeID` values.** Nothing in the export table encodes the
   actual runtime integers behind `CFStringGetTypeID` et al. swift-corelibs-foundation
   publishes constants for *its* runtime, which are not evidence for Apple's;
   I deliberately did not cite them.

---

## 5. Wrapper issues for the Curator

- **`nm-symbols` / `otool-exports` / `strings-grep` cannot read
  dyld-shared-cache-backed images on macOS 27.** All three return
  `tool-failed "binary not found"`. Every `scripts/bin/*` wrapper is currently
  unusable against system frameworks on this host — which is most of the
  corpus. Worth either a `dyld_info` fallback or an explicit "cache-backed
  image" status rather than the misleading "binary not found".
- **`class-dump` is not installable.** `brew install class-dump` fails with
  *"No available formula with the name class-dump"* (Homebrew only suggests
  the unrelated `classads`). The briefing's install hint is wrong for current
  Homebrew. `class-dump-types` therefore emits `tool-not-installed`, which is
  the correct wrapper behaviour, but ObjC-class dumping of CF was **not**
  possible this sprint and no claim rests on it.
- All five wrappers respond correctly to `--help`; `class-dump-types`
  correctly reports its missing-tool state rather than crashing.