---
name: switch-shadow-resolution-pchtxt
description: >-
  Author Nintendo Switch shadow-resolution exefs pchtxt mods by locating the
  engine's shadow-map sizing in IDA and forcing a larger depth-shadow texture. Use
  when asked for a "shadow resolution mod", "sharper/higher-res shadows", "shadow
  map size", or any pchtxt that rewrites a shadow-map dimension for a Switch title
  (Ryujinx / Atmosphere).
---

# Switch shadow-resolution pchtxt mods

Raises the size of the sun/cascade depth-shadow map so shadow edges stop being
blocky. Derived working on the Splatoon 2 / Blitz (gsys + agl `sdw`) engine.

Deliver patches as pchtxt only. Never modify the game dump. Open IDBs **in place**
(no copies).

Related: `switch-resolution-pchtxt` (render resolution — **read its §2b**, the
shadow map competes for the same GPU pool) and `switch-lod-bias-pchtxt`.

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
endings. `RVA = IDB_addr - imagebase` (Blitz IDBs load at `0x7100000000`).

## 1. Where the size actually comes from

Do **not** go looking for a hardcoded shadow constant — in a modern engine there
usually isn't one. The chain in Blitz:

```
gsys::ModelSceneShadow::drawDepthShadow(DrawContext*, ModelSceneContext*)   // per frame
    -> agl::sdw::ShadowMap::setSize(Vector2<int>)                           // stores w/h
    -> agl::sdw::DepthShadow::allocShadowMap()
        -> agl::sdw::ShadowMap::allocDepthBuffer(dc, cascade_num, ...)
            -> agl::utl::DynamicTextureAllocator  (texture name "shadow_map_depth")
```

The dimensions are **env parameters**, not constants:
`gsys::ModelSceneConfig::depth_shadow_tex_width` / `_height`
(`agl::utl::Parameter<int>` at fixed struct offsets, Blitz: `+0x1818` / `+0x1838`).
Their in-code defaults are only placeholders — in Blitz the width default decodes
to `ORR W8,WZR,#0x400` = 1024 and the **height default is `MOVN W8,#0` = -1**, a
sentinel proving the real values arrive from a loaded env/scene archive. So
patching the constructor defaults is pointless; patch the **read site** instead.

## 2. The clamp that defeats a resolution mod

`drawDepthShadow` scales the configured size by the viewport ratio and then takes
a **minimum**, so the shadow map can shrink but never grow:

```c
scale = max(viewportW/1280.0, viewportH/720.0);      // 1.0 at 720p, 3.0 at 4K
w = (int)(cfgW * scale);  if (w <= cfgW) cfgW = w;   // min(scaled, configured)
if (w < 32) cfgW = 32;                                // floor
// ... same for height ...
setSize({cfgW, cfgH});
```

This is why raising the render resolution alone leaves shadows exactly as they
were. Two ways to attack it:

**(a) Force an absolute size — preferred.** Overwrite the two config *reads* with
immediates:
```
LDR W9,[X8,#<cfg_w_off>]   ->   MOVZ W9,#SIZE
LDR W8,[X8,#<cfg_h_off>]   ->   MOVZ W8,#SIZE
```
`MOVZ Wd,#imm` = `0x52800000 | (imm<<5) | Rd`. For 2048 (`0x800`): W9 =
`09008152`, W8 = `08008152`. For 4096 (`0x1000`): W9 = `09008252`, W8 =
`08008252`.

The min-clamp then works *for* you: with any viewport ≥ the reference size the
scaled value is ≥ your immediate, so the clamp keeps the immediate exactly. The
preceding `LDR X8,[X21,#8]` (the config pointer load) becomes dead — harmless.
This also makes the size deterministic across scenes, bypassing whatever each
stage's env archive sets.

**(b) Remove the cap** so the size tracks the render resolution: rewrite the two
`CSEL Wd, Wcfg, Wscaled, GT` min-selects as `MOV Wd, Wscaled`
(`ORR Wd, WZR, Wscaled`). Elegant, needs no knowledge of the base value, but does
nothing at native resolution and at 4K multiplies each axis by 3 (**9× the
memory**) — easy to blow the pool with.

Prefer (a): one predictable number, and it works standalone.

## 3. Memory — the part that bites

The shadow map is allocated **per frame from the same fixed
`DynamicTextureAllocator` pool** as the post-effect/DoF buffers, and it is a
texture *array* — one slice per cascade. Cost scales with the **square** of the
size times the cascade count, so 1024 → 2048 is 4× and 1024 → 4096 is 16×.

Consequences:
- A shadow mod on an otherwise-stock game can exhaust the native pool by itself.
- Ship it alongside the resolution mods, which already enlarge that pool
  (`switch-resolution-pchtxt` §2b), and say so in the file header.
- **Do not** duplicate the pool/heap patch lines into the shadow pchtxt if a
  resolution mod also patches those offsets — two enabled mods writing the same
  offset different values is order-dependent. Keep each offset owned by exactly
  one mod folder.

Failure signature is the pool one: abort in
`agl::utl::DynamicTextureAllocator::alloc_` with
`"[%s] alloc failed from [%s]. alloc size:%d free size:%d"`.

## 4. Finding it in a new build
1. Search the mangled-name/string area for `ShadowMap` / `DepthShadow` to confirm
   the engine uses `agl::sdw`. `agl::sdw::ShadowMap::setSize` is the pivot —
   `xrefs_to` it and ignore the cutscene/`GfxEnvChanger` and masked-spot-light
   callers; the per-frame scene caller is `drawDepthShadow`.
2. In `drawDepthShadow`, find the pair of `LDR Wn,[Xcfg,#imm]` feeding the
   `SCVTF/FMUL/FCVTZS/CMP/CSEL` size math just before the `setSize` call.
3. `get_bytes` those two words. In Blitz all three builds shared the identical
   encoding `09 19 58 B9 / 08 39 58 B9` at the same offset *within* the function,
   so once you have one build, locate `drawDepthShadow` in the others by symbol and
   apply the same relative offset — then re-verify the bytes.
4. Confirm the parameter names (`depth_shadow_tex_width` / `_height`) exist in the
   string table to be sure you have the sun shadow and not a spot-light shadow.

## 5. Verification checklist
1. `get_bytes` both original words; confirm they are the two config loads.
2. Check the log applied them: `ModLoader Patch: Patching address offset ...`.
3. Watch for a `DynamicTextureAllocator::alloc_` abort — that is the pool, not a
   bad offset (§3).
4. Shadows should visibly sharpen at the same render resolution. If they do not
   change at all, you likely patched a masked-light shadow path instead of the
   cascade one, or the scene's env archive drives a different code path.

## 6. Layout

Group by **title ID first** (Ryujinx resolves mods per application ID; title IDs
differ **by region**). One mod folder per shadow size so the user picks one:

```
<Game> (<TITLEID>)/
  [Shadow Resolution 2048]/exefs/<Build label>.pchtxt
  [Shadow Resolution 4096]/exefs/<Build label>.pchtxt
```
One pchtxt per build inside each `exefs/`; only the matching `@nsobid` applies.
