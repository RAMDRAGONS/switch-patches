---
name: writing-double-buffer-patches
description: Use when checking whether a Switch game is double or triple buffered, forcing a 2-texture NVN swapchain to cut input latency, or writing a [Double Buffering] pchtxt, including games that switch between 2 and 3 textures at runtime (sead GameFrameworkNx, Unity NX player, nn::gfx SwapChain, raw NVN)
---

# Writing double buffer patches

## Overview

The swapchain size is the texture count passed to `nvnWindowBuilderSetTextures`, unless a later `nvnWindowBuilderSetNumActiveTextures` / `nvnWindowSetNumActiveTextures` lowers the active count. Trace that number back to its source, patch the source to 2, and close every runtime path that raises it back to 3.

**REQUIRED BACKGROUND:** using-ida-mcp (prelude, session rules), writing-switch-pchtxt (encoders, `pchtxt_check`, file conventions).

## Workflow

1. **Back up and open** the IDB (`main.i64.bak`). If the folder has stray `.id0/.id1/.nam/.til/.$$$` files, or open fails ("indeterminate unpacked state", "error 4"), rebuild from `Game Dumps/Switch/<Game>/<ver>/exefs/main` in `~/.cache/switch-re/<name>/`. If the NSO `.text` file offset (header +0x10) isn't 0x100, the NSO loader opens it as SNES: convert with analyzing-switch-arm64-in-ida's `nso2elf.py` at base 0 first. Copy the new `.i64` beside the old files under a new name; leave the old ones alone.
2. **Survey:** load the prelude, then `exec(open('<this dir>/nvnswap.py').read())` and `swap_report()`. The function that reads every slot is the bootstrap loader; ignore it.
3. **Read the `SetTextures` caller** and follow the count argument to its source. Identify the engine from the table below.
4. **Check every `nvnWindowSetNumActiveTextures` user.** That is runtime switching. A game that starts with 2 but can go to 3 still needs a patch.
5. **Prove 2 is safe:** the render target must be picked by the acquired index (`nvnWindowAcquireTexture` out-param), not by a `frame % 3` rotation. Arrays sized for 3 are fine with 2, but a fixed rotation of 3 is not.
6. **Patch the source of the count**, run `try_patch`, write the pchtxt, then run `pchtxt_check`.

## Engines

| Engine | Count source | Patch |
|---|---|---|
| sead `GameFrameworkNx` (ARMS, Toad, Splatoon 2 builds) | `CreateArg.isTripleBuffer` (+0x1D) copied into the framework, read as `LDRB W1,[X19,#0xBD]` (or `[X19,X8]`, X8 = 0x206D in symbol builds) before `DisplayBufferNvn::setTripleBuffer` (`TST W1,#1; MOV W8,#2; CINC; STRB [X0,#0x49]`). Find it with `find_buffer_count_setter()`. | The flag load → `MOV W1,#0` |
| Newer sead (Splatoon 3, Wonder, ACNH, Tomodachi) | The setter is inlined (`LDRB W9,[X19,#0xA5 or 0xBD]; …; CINC; STRB [X8,#0x51/0x59/0x49]`), and present_ also has a **runtime switcher**: slow frames raise 2→3, short frames lower 3→2, and a request byte (-1 none, 0 → 2, 1 → 3) forces either. Use `find_count_writes(field, lo, hi)`. | 1) flag load → `MOV W9,#0`; 2) the `B.LE` that skips the 2→3 auto switch → `B` same target; 3) request-1 path: `CMP W9,#3` → `CMP W9,#2` and `MOV W1,#3` → `MOV W1,#2` |
| nn::gfx `SwapChain::Initialize` (Clubhouse, Rhythm Heaven, TTYD, Bayonetta 2, HWDE) | `SwapChainInfo` byte 0 (`LOBYTE(info) = N`), set by the caller or copied from a config block | The immediate → `#2` |
| Raw NVN (Astral Chain, XC2, XCDE, Dread) | Immediate in `SetTextures(builder, N, textures)` | `MOV W1,#3` → `#2` |
| Unity NX player (SMRPG, Theatrhythm) | `NX_CreateBackBuffersAndWindow` creates 3 textures, and the active count comes from GfxDevice +0x1E2C (max queued frames, ctor default `MOV W8,#3`), clamped to 2..3 and reapplied each frame | 1) ctor default → `#2`; 2) builder `SetNumActiveTextures` arg (`LDR W1,[Xn]`) → `MOV W1,#2`. First confirm the game never sets it: no `set_maxQueuedFrames(System.Int32)` IL2CPP icall string, only the getter |

To check a CreateArg value, decompile the framework ctor (`memcpy(fw + base, arg, n)` or field copies) to map the framework offset back to the arg offset. Then read the caller's stack stores in disassembly: an `STURH`/`STR` of a wider value can cover +0x1D. Also check the game's `overwriteFrameworkCreateArg`-style virtual hook, which runs after the defaults.

## pchtxt shape

Folder `[Double Buffering]/exefs/<ver>.pchtxt`, CRLF line endings. Copy the header and footer from the game's other pchtxts. Give one `//` line per patch site saying what it was, and use no blank lines inside `@enabled`.

```
@enabled
// initial buffer count: isTripleBuffer read as false
037B84A4 09008052   // MOV W9,#0 (was LDRB W9,[X19,#0xBD])
// slow-frame auto switch from 2 to 3 never fires
037B9834 13000014   // B to the present call (was B.LE)
@stop
```

## Common mistakes

| Mistake | Fix |
|---|---|
| Patched only the initial count on a game with `SetNumActiveTextures` users | Runtime switching re-raises it. Patch every route to 3. |
| Took the `STR X0` right after the name string as that proc's slot | That stores the *previous* proc's result; `proc_slots` skips to the call first |
| Survey found nothing in a stripped IDB | Slots are written through GOT pointers and the string list misses names; `nvnswap.py` handles both |
| Concluded "double" from a 2/3 setter alone | Read the actual flag value at the CreateArg build site and any game hook after it |
| Lowered a count without checking consumers | Confirm the views/targets are indexed by the acquired index. A fixed `% 3` ring of fences or command memory (Bayonetta 2) is separate and can stay. |
| GBAtemp double→triple collection thread used as proof | It lists games that are double buffered (XC2/XCDE/XC3, TTYD), but verify against the binary: versions differ |
