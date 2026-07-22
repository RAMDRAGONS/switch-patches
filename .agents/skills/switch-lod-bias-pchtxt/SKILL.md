---
name: switch-lod-bias-pchtxt
description: >-
  Author Nintendo Switch texture level-of-detail (LOD) exefs pchtxt mods by
  locating the nn::gfx sampler mip-LOD-bias setup in IDA and forcing a negative
  bias. Use when asked for an "LOD mod", "LOD bias", "sharper textures", "texture
  sharpening", or any pchtxt that rewrites a sampler LOD bias for a Switch title
  (Ryujinx / Atmosphere).
---

# Switch texture LOD-bias pchtxt mods

Forces the texture sampler mip-LOD bias to a negative value so the GPU picks a
higher-resolution mip level than the distance-based default — the classic
"sharper textures" mod. Small, self-contained, and independent of resolution.

Deliver patches as pchtxt only. Never modify the game dump. Open IDBs **in place**
(no copies).

Related: `switch-resolution-pchtxt` (render resolution — often shipped alongside
this as a separate mod folder) and `switch-shadow-resolution-pchtxt`.

## 0. pchtxt format (Ryujinx `IPSwitchPatcher`)

```
@nsobid-<UPPERCASE_BUILDID>        # NSO ModuleId (file offset 0x40, trailing zeros trimmed)

# free-form title comment

@flag print_values                 # optional: logs each patched value
@flag offset_shift 0x100           # pchtxt offsets are then raw RVAs (see below)

// C-style comments are allowed anywhere
@enabled
<OFFSET_HEX> <BYTES_HEX>           # bytes are in MEMORY ORDER (little-endian per instr)
@stop
```

- **A blank line resets `@enabled` to off.** Comment lines between patch lines are
  fine; a blank line ends the block.
- **Bytes are memory order** — the little-endian encoding of each 32-bit ARM64
  instruction.
- **Offset base.** Ryujinx adds `offset_shift`, then `MemPatch` subtracts the NSO
  `protectedOffset = 0x100`. With `@flag offset_shift 0x100` the **pchtxt offset
  equals the file RVA**. Write RVAs directly.
- **RVA from an IDB address**: `RVA = IDB_addr - imagebase` (Blitz IDBs load at
  `0x7100000000` even when the health probe reports `imagebase 0x0`).
- Filename is arbitrary; Ryujinx matches on `@nsobid` only, so files for every
  build can sit side by side in one mod folder.
- **Line endings: CRLF.**

## 1. The mechanism

In `nn::gfx`, `SamplerImpl<...>::Initialize` copies `SamplerInfo.lodBias` (a float
at struct offset **0x10**) into `s0` and calls `nvnSamplerBuilderSetLodBias`:

```
LDR S0, [X20,#0x10]                ; <- patch this
LDR X8, [X8,#...]                  ; pfnc_nvnSamplerBuilderSetLodBias
LDR X8, [X8]
MOV X0, SP
BLR X8
```

Replace `LDR S0,[Xn,#0x10]` with **`FMOV S0, #-1.0`** = bytes `00103E1E`
(word `0x1E3E1000`). One line, one build-specific offset.

Because this rewrites the *source* of the bias rather than any individual
sampler's data, it applies to every sampler the title creates.

## 2. Finding it

The setter calls go through GOT pointers with a stable idiom
`LDR X8,[X8]; MOV X0,SP; BLR X8` = `08 01 40 F9 E0 03 00 91 00 01 3F D6`. The LOD
bias load sits between the `setLodClamp` (`LDP S0,S1,[Xn,#8]`) and `setLodBias`
calls. Search this masked fingerprint (register/PC-relative bytes wildcarded):

```
?? ?? 41 2D ?? ?? ?? ?? 08 01 40 F9 E0 03 00 91 00 01 3F D6 ?? ?? ?? ?? ?? ?? 40 BD ?? ?? ?? ?? 08 01 40 F9 E0 03 00 91 00 01 3F D6
```

It is unique per build. The `LDR S0,[Xn,#0x10]` to patch is at **match + 0x18**.
Always `disasm` that address and confirm the following call resolves to
`SetLodBias` before trusting it; confirm by symbol too when one is present
(`nn::gfx::detail::SamplerImpl<...>::Initialize`).

The offset is stable across closely related builds of the same engine but **not
identical** — re-derive it per build rather than reusing a number.

## 3. Choosing the bias

`FMOV Sd, #imm` uses an 8-bit immediate: word = `0x1E201000 | (imm8 << 13) | Rd`.

| value | imm8 | word (Rd=0) | bytes    |
|-------|------|-------------|----------|
| -1.0  | 0xF0 | 0x1E3E1000  | 00103E1E |
| -0.5  | 0xF8 | 0x1E3F1000  | 00103F1E |
| -2.0  | 0xE0 | 0x1E3C1000  | 00103C1E |

`-1.0` is the community default and equals one full mip level. Going past `-1.0`
increases aliasing and texture-cache pressure fast; prefer `-1.0` unless asked.

## 4. Verification checklist
1. `get_bytes` the original 4 bytes; confirm it is `LDR S0,[Xn,#0x10]` and not a
   neighbouring float load.
2. `disasm` forward a few instructions and confirm the `SetLodBias` call.
3. Confirm `@nsobid` against the NSO ModuleId (file offset 0x40, trailing zeros
   trimmed). A wrong build id means the patch silently never applies — in a Ryujinx
   run log the tell is the `ModLoader ApplyProgramPatches: Matching IPSwitch patch
   ... bid=` line, followed by `ModLoader Patch: Patching address offset ...`.
4. Re-read the written file: contiguous `@enabled` block, CRLF, RVA offsets.

## 5. Layout

Group by **title ID first** (Ryujinx resolves mods per application ID; title IDs
differ **by region**, so builds of the same game can land in different folders —
read the real one from the log's `QueryContentsDir: Searching mods for Application
<TID>` line). LOD gets its own self-contained mod folder:

```
<Game> (<TITLEID>)/
  [Level of Detail]/exefs/<Build label>.pchtxt   # e.g. "20170328 Proto.pchtxt"
```

One pchtxt per build inside the single `exefs/`; only the build whose `@nsobid`
matches is applied. Header/description wording and any repo-URL footer are the
author's — preserve them across edits.
