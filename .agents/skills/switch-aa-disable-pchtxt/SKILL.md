---
name: switch-aa-disable-pchtxt
description: >-
  Author Nintendo Switch exefs pchtxt mods that disable every anti-aliasing pass
  a game runs (FXAA, SMAA, ReduceAA, DLAA, temporal AA, pseudo AA and their
  camera jitter), using the engine's own no-AA path. Use when asked to "disable
  anti-aliasing", "disable FXAA/SMAA/TAA", "remove the blur / AA", or to audit a
  title for AA passes (Ryujinx / Atmosphere), including agl/gsys FilterAA
  titles (Splatoon 2/3, ARMS, Tomodachi Life, SMBW, ACNH), ActionLibrary
  (Captain Toad), Monolith (Xenoblade), Bezel, PlatinumGames and MercurySteam.
---

# Switch "Disable Anti-Aliasing" pchtxt mods

Goal: one `[Disable Anti-Aliasing]` mod per game that turns off **every** AA
pass, not just one mode. Find every AA pass first, then make the renderer take
the path it already uses when AA is off. Patch code, not config defaults, so
scene/env/byml files cannot turn AA back on.

Deliver pchtxt only; never modify the game dump. Use the IDA MCP with the
`using-ida-mcp`, `analyzing-switch-arm64-in-ida` and `writing-switch-pchtxt`
helpers (load them in the first `execute_python` after each open). Back up the
IDB first (`cp main.i64 main.i64.bak`). Run `pchtxt_check(path)` on every file.

Related: `switch-resolution-pchtxt`, `switch-lod-bias-pchtxt`,
`switch-shadow-resolution-pchtxt`.

## 1. Audit: find every AA pass

1. String census: `strs(r'(?i)fxaa|smaa|mlaa|dlaa|taa|temporal|antialias|jitter|aa_type|pseudoaa')`.
   Ignore `nvnMultisample*` (NVN proc names, always present) and Unity engine
   strings. `jitter` is often unrelated (cloud noise, shadow sampler, light
   scattering uniforms): check what registers it.
2. For each AA shader/program, find who **draws** with it, not who loads it.
   Astral Chain loads MLAA and DLAA programs that nothing draws.
3. Look for game-side AA bolted onto agl FilterAA's **draw callback** (mode
   2/3): Splatoon 2 binds `Cmn::SMAA` there in every GfxMgr scene, so SMAA, not
   FXAA, is its live AA; ARMS binds a module with FXAA / luma FXAA / TAA / SMAA.
4. Look for **projection jitter** that only makes sense with a temporal
   resolve (ARMS temporal modes, Captain Toad pseudo AA, Xenoblade tmaa). Kill
   it together with the resolve or the image shakes.
5. A pass that also does other work (copy to output, sepia, tonemap) must keep
   running; neutralise only its AA.

## 2. Patch patterns

| Engine | Where AA is decided | Patch |
|---|---|---|
| agl/gsys (Splatoon 2, ARMS) | "FilterAA enabled" test (scene allows AA, `enable`, `scale > 0`) inlined in calcView, allocRenderBuffer, drawFinalImage (+ out-of-line isFilterAAEnabled) | Replace each `LDR S0,[X,#scale]` with `B` to its false result. All copies must agree. |
| gsys ModuleSystem-era (Splatoon 3, SMBW, Tomodachi, ACNH) | One test in the final-image pass (`LDRB allow; CBZ; LDR S0 scale; FCMP; LDRB enable; CCMP; CSET`) | `B` from the scale load to the `MOV Wn, WZR` block |
| ActionLibrary (Captain Toad) | `GraphicsSystemInfo::preDrawGraphics` rewrites FilterAA enable each frame; drawView applies pseudo-AA offset | NOP the CBZ so enable is always stored false; `B` past the pseudo-AA offset |
| Monolith (XC2, XCDE) | Text post-effect params `AntiAliasing` and `tmaa` copied into the render state (+0xFC, +0x111); frame picks no-AA final composite when both are off | Store `WZR` at every write of the two fields (reset, mode-1 default, param copy, any scene that forces tmaa) |
| Bezel (Clubhouse) | Tonemap program pick (FXAA folded in) + PostFx "FXAA" effect `IsEnabled` vfunc | Plain tonemap program; `MOV W0,#0; RET` in the effect's IsEnabled |
| PlatinumGames | One flag bit/AND decides DLAA or SMAA chain | Zero the flag / NOP the bit test |
| MercurySteam (Dread) | Separate FXAA draw after a plain copy | NOP the FXAA call |
| Intelligent Systems gfx (TTYD) | Pass flags +0x58 bits 0-2 = skip; the previous pass then writes the output itself. FXAA pass also applies script sepia (`SetSepiaColorFilter`, epilogue only) | Register FXAA with bit 0 set; make SetSepiaColorFilter clear bit 0 while alpha != 0; zero rcpFrame so FXAA is a no-op while sepia runs |

Never redirect an **in-place** filter (source texture == target) to agl's
`drawTexture` pass-through: copying a texture onto itself flickers in emulators.
Skip the call instead (Tomodachi snapshot renderer), or gate it off upstream.

`gsys_aa.py` (this directory; `exec` it after the pchtxt helpers) holds `gsys_aa_gates(start, end)` (finds the
`LDRB; CBZ; LDR S0; FCMP S0,#0.0` gates, keyed by enable/scale offsets) and
`gate_patch()` (prefers a following `B.LE` target, which zeroes the result
register; the CBZ target can skip that zeroing).

## 3. Known sites (this repo)

| Title / build | Sites |
|---|---|
| Splatoon 2 5.5.2 | gates `01803738`, `01805078`, `0180539C` (scale `0xE48`) |
| Splatoon 2 QA B2 / protos / Testfire | 4 gates each incl. isFilterAAEnabled (scale `0xA58`) |
| Splatoon 3 11.3.0 / 11.2.0 | `047012DC` / `0470096C` |
| ARMS 5.5.1 | gates `00A25934`, `00A26ED8`, `00A27110`; jitter `001732A4` NOP |
| Captain Toad 1.4.2 | `002DBE6C` NOP, `002DE86C` B |
| Tomodachi 1.0.4 | gates `001B27C4`, `001C3CB8`; snapshot call `005943D4` NOP |
| SMBW 1.2.1 | `0015EE10` |
| ACNH 3.0.3 | view setup `039378E0` MOV WZR; final image `039395B0` |
| Clubhouse 2.0.1 | `002F9DD8`, `00766978` |
| Dread 2.1.0 | `001DACF8` |
| Astral Chain 1.0.1 | `00402AE0` |
| Bayonetta 2 1.2 | `00979EFC` |
| XC2 3.0.1 | `007A098C`, `007A1278`, `007A12F4`, `007A12FC` |
| XCDE 2.0.0 | `00698198`, `006B1CA8`, `006B2588`, `006B2620`, `006B2628` |
| TTYD 1.0.1 | register `0035EAF4`; sepia toggle cave `005E922C`; rcpFrame stores in `sub_7100255490` / `sub_7100255AB4` |

No AA found: Hyrule Warriors DE, Rhythm Heaven Groove. SMRPG ships with no AA
(Unity URP asset). Theatrhythm (Unity built-in pipeline) keeps its AA settings
in IL2CPP metadata/assets, not the main binary.

## 4. Layout

```
<Game> (<TITLEID>)/
  [Disable Anti-Aliasing]/exefs/<Build label>.pchtxt
```

One pchtxt per build in the single `exefs/`; only the matching `@nsobid`
applies. CRLF, `@flag offset_shift 0x100`, no blank lines inside `@enabled`.
Header comments explain every AA pass the game has and how each is stopped.
