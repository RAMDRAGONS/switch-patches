---
name: switch-fxaa-disable-pchtxt
description: >-
  Author Nintendo Switch exefs pchtxt mods that disable FXAA post-process
  anti-aliasing by redirecting the agl/gsys FilterAA draw dispatch to its
  pass-through copy. Use when asked to "disable FXAA", "turn off anti-aliasing",
  "remove the blur / AA", "no FXAA", or any pchtxt that switches off a Switch
  title's post-AA filter (Ryujinx / Atmosphere), especially on Nintendo agl/gsys
  engines (Splatoon 2 "Blitz", Tomodachi Life "Colony", and relatives).
---

# Switch FXAA-disable pchtxt mods

Disables the FXAA post-process anti-aliasing pass so the frame is presented
un-blurred, **without** touching the other AA modes (SMAA / ReduceAA) in case a
scene ever selects them. Derived on the agl/gsys `agl::pfx::FilterAA` effect shared
by Splatoon 2 (Blitz) and Tomodachi Life (Colony).

Deliver patches as pchtxt only. Never modify the game dump. Open IDBs **in place**
(no copies).

Related: `switch-resolution-pchtxt`, `switch-lod-bias-pchtxt`,
`switch-shadow-resolution-pchtxt` — same engine family, same IDB/pchtxt conventions.

## 0. pchtxt format (Ryujinx `IPSwitchPatcher`)

```
@nsobid-<UPPERCASE_BUILDID>        # NSO ModuleId (file offset 0x40, trailing zeros trimmed)

@flag print_values
@flag offset_shift 0x100           # pchtxt offset then == raw RVA

@enabled
<OFFSET_HEX> <BYTES_HEX>           # memory order (little-endian per instruction)
@stop
```
A **blank** line ends an `@enabled` block (comment lines do not). CRLF line
endings. Bytes are the little-endian encoding of each 32-bit ARM64 instruction.
`RVA = IDB_addr - imagebase` — **Blitz and Colony IDBs load at `0x7100000000`**
even when the health probe reports `imagebase 0x0`. Ryujinx matches on `@nsobid`
only, so one pchtxt per build can sit side by side in a single mod folder.

## 1. The mechanism

`agl::pfx::FilterAA::draw` is the whole anti-alias pass. It is **not virtual** —
it is called directly from `gsys::ModelSceneBuffer::drawFinalImage` once per frame.
Its shape (identical across the family, modulo field offsets and whether the
compiler emitted a jump table or a compare chain):

```c
// pass-through if the filter is off or has no scale
if (this->enable == 0 || this->scale <= 0.0f) { drawTexture(...passthrough...); }
else switch (this->antialias_type) {          // the FXAA_TYPE enum
    case 0: FXAA(...);      break;             // <- the one to kill
    case 1: ReduceAA(...);  break;
    case 2: SMAA(...);      break;
    case 3: callback(...);  break;             // indirect, via this+cb
    default: /* invalidate only, no copy */ ;
}
```

The default `antialias_type` is **0 (FXAA)** and default `enable` is **1**, so on a
stock game the FXAA case is the live path. The `else` branch is a plain
`agl::utl::ImageFilter2D::drawTexture` copy — the exact "no AA" output we want.

## 2. The patch — redirect FXAA to the pass-through

**Do not** disable the whole filter (that also kills SMAA/ReduceAA and is
config-overridable) and **do not** send FXAA to the `default` case (it does no
image copy → garbage output). Redirect **only** the FXAA case into the function's
existing disabled/pass-through block, by overwriting the **first instruction of the
FXAA case handler** (or, on the compare-chain build, the branch that guards the
FXAA fall-through) with an unconditional `B` to the pass-through label.

This patches code, not a config default, so a byaml/env archive that re-sets
`enable`/`antialias_type` cannot undo it.

`B` encoding: `word = 0x14000000 | (((target - PC) >> 2) & 0x03FFFFFF)`.
- Forward example (5.5.2): PC `…ACF210` → target `…ACF228`, disp `+0x18` →
  `0x14000006` → bytes `06000014`.
- Backward example (Colony): PC `…A3E70` → target `…A3DE0`, disp `-0x90` →
  `0x17FFFFDC` → bytes `DCFFFF17`. **Verify backward displacements against a `B`
  already present in the same function** (e.g. a `break` that jumps to the epilogue)
  — read its bytes and confirm your two's-complement matches.

On the older compare-chain layout (Splatoon 2 QA build) the FXAA case is the
fall-through after a `CBNZ Wt,<post-draw>`; turn that `CBNZ` into a `B` to the
pass-through label instead. `CBNZ` word `0x35000000|(off19<<5)|Rt`; a same-length
`B` replaces it cleanly.

## 3. Finding `draw` in a new build

RTTI and the `antialias_type`/`FXAA_TYPE` literals are stripped in retail; the
config-param strings and the shader sampler names survive. Work strings →
structure → function; **do not** lead with byte signatures (jump table vs. compare
chain and split immediate offsets defeat them).

1. **`"aglfila"`** (or `"filter_aa"`) → data-xref → the **FilterAA constructor**.
   It stores the vtable at `this+0` and writes each param's **default value**,
   which hands you the field offsets: `antialias_type` = an `int` default `0`,
   `enable` = a `bool` default `1`, spaced a fixed stride apart. Note both.
2. `draw` is not in the vtable, so find it by a **unique string in a helper it
   calls**: **`"temp_target"`** (the FXAA function also refs **`"luma"`**) →
   data-xref → the **FXAA sub-function** → `xrefs_to` (code) that sub-function → its
   lone caller is `draw`. Note: on Colony, `draw`/FXAA live in a **different text
   region** than the constructor (ctor `0x71005xxxx`, draw `0x71021Axxxx`) — do not
   assume proximity or trust a region-scoped search to be exhaustive.
3. **Cross-check the symbol-bearing Splatoon 2 QA build** (`…/Blitz/1.1.0 QA B2/`)
   — it keeps mangled names (`_ZNK3agl3pfx8FilterAA4drawE…`,
   `…FilterAA4FXAAE…`, `agl::utl::ImageFilter2D::drawTexture`). Disassemble the
   named `draw` there to confirm the case order (0=FXAA,1=ReduceAA,2=SMAA) and the
   pass-through target, then map onto the stripped build by structure + the field
   offsets from step 1.
4. `decompile` the candidate and confirm it reads `enable`/`antialias_type` at the
   offsets you predicted and dispatches to the FXAA helper in case 0.

## 4. Known sites (this repo)

`RVA = IDB_addr − 0x7100000000`. The **compare-chain** builds (dev/proto/QA and
Testfire — same 9-arg `draw` of size ~0x250) turn the `CBNZ` guarding the FXAA
fall-through into a `B` to the pass-through (disp `+0x30` → `0C000014`; the CBNZ's
`Rt` sets byte0, so W8=`88…`, W9=`89…`). The **jump-table** retail builds (5.5.2,
Colony 1.0.4) overwrite the FXAA case's first instr `MOV X0,X21` (`E0 03 15 AA`)
with a `B` to the pass-through. All original bytes were `get_bytes`-verified.

| Build (title) | `@nsobid` | draw / fields | RVA | orig → patch |
|---|---|---|---|---|
| **QA B2** (Global 01003BC…) | `FA3897E0FADDD49C69ED00F23E705B3E` | `0x71018B56DC`; type@`0x428`, enable@`0x448` | `018B583C` | `88020035` CBNZ → `0C000014` |
| **5.5.2** (Global 01003BC…) | `592C7051A4E620563D0296096D8F0AC5` | `sub_7101ACF158`; type@`0x738`, enable@`0x758`; FXAA `sub_7101ACF330` | `01ACF210` | `E00315AA` → `06000014` |
| **Mar-28-2017 proto** (JP 01003C7…) | `51A5F17583DE73E0038772960B42E091` | `0x710173A0A4`; type@`0x428` | `0173A204` | `88020035` CBNZ → `0C000014` |
| **Mar-24-2017 proto** (JP 01003C7…) | `1F1C44F29E77B5D6C7AA5A518E724318` | `0x71017102DC`; type@`0x428` | `0171043C` | `88020035` CBNZ → `0C000014` |
| **Global Testfire** (010000A0…) | `0F129135D8A7621C9E4940B0C3808BF0` | `0x71011B2118`; type@`0x428` | `011B21EC` | `89020035` CBNZ → `0C000014` |
| **Tomodachi 1.0.4** (010051F0…) | `B39FEF373FB12154385D012AAB3BC99EF2944470` | `sub_71021A3CD0`; ctor `sub_710052CD98`; type@`0x748`, enable@`0x768`, scale@`0x9A0`; FXAA `sub_71021A3EB8` | `021A3E70` | `E00315AA` → `DCFFFF17` |

Dev/proto/QA/Testfire Blitz builds keep the `agl::pfx::FilterAA::draw` symbol — use
`list_funcs *FilterAA*draw*` (pick the 9-arg `…SD_bSD_` overload) instead of the
string hunt. Field offsets shift ~+16 bytes between Blitz 5.5.2 and Colony because
Colony's base class is larger; always re-read them from the constructor, never reuse
a number.

## 5. Verification checklist
1. `get_bytes` the original 4 bytes at the site; confirm it is the FXAA case entry
   (or the QA `CBNZ`) and not a neighbouring `MOV`/branch.
2. Confirm the `B` target is the function's pass-through block
   (`ImageFilter2D::drawTexture` copy), **not** the `default` case (no copy) and not
   the FXAA helper.
3. Recompute the displacement; for a backward `B`, match it against an existing
   backward `B` in the same function.
4. Confirm `@nsobid` = the NSO ModuleId (file offset 0x40, trailing zeros trimmed).
   Wrong id ⇒ patch silently never applies; the Ryujinx log tell is
   `ModLoader ApplyProgramPatches: Matching IPSwitch patch … bid=` then
   `ModLoader Patch: Patching address offset …`.
5. Re-read the file: contiguous `@enabled` block, CRLF, RVA offset.
6. **Confirm the feature exists before promising a patch.** Not every engine ships
   FilterAA — e.g. Rhythm Heaven Groove ("Aloha") has no FXAA at all. Search the
   string table for `FXAA_TYPE` / `antialias_type` / `aglfila` first.

## 6. Layout

Group by **title ID first** (Ryujinx resolves mods per application ID; title IDs
differ **by region** — read the real one from the log's
`QueryContentsDir: Searching mods for Application <TID>` line). FXAA-disable is its
own self-contained mod folder:

```
<Game> (<TITLEID>)/
  [Disable FXAA]/exefs/<Build label>.pchtxt   # e.g. "5.5.2.pchtxt", "1.0.4.pchtxt"
```

One pchtxt per build in the single `exefs/`; only the matching `@nsobid` applies.
Header/description wording and any repo-URL footer are the author's — preserve them.
