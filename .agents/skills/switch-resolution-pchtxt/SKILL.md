---
name: switch-resolution-pchtxt
description: >-
  Author Nintendo Switch render-resolution exefs pchtxt mods by reverse-engineering
  the game's packed scan-buffer size constant in IDA, plus the GPU pools, heap
  partitions, UI canvas and dynamic-resolution clamp that must be patched with it.
  Use when asked to make a "1920x1080 / 1440p / 4K resolution mod", an
  "anti-dynamic-resolution" pin, or any pchtxt that rewrites a packed WxH constant
  for a Switch title (Ryujinx / Atmosphere).
---

# Switch resolution pchtxt mods

This skill captures the end-to-end method for producing render-resolution patches
as **exefs pchtxt** (IPSwitch) mods. It was derived working on the Splatoon 2 /
Blitz (Cstm/Lp + gsys/agl + nn::gfx NVN) engine, but the technique generalizes to
any title that stores its output resolution as a packed 64-bit `width|height`
constant.

Sibling skills, each its own mod folder: `switch-lod-bias-pchtxt` (texture LOD
bias), `switch-shadow-resolution-pchtxt` (shadow-map size — it draws from the
same GPU pool as §2b, so read them together) and `switch-framerate-pchtxt`
(frame pacing — pairing it with a resolution mod multiplies the GPU cost).

Deliver patches as pchtxt only. Never modify the game dump. Open IDBs **in place**
(no copies).

## 0. pchtxt format (Ryujinx `IPSwitchPatcher`)

```
@nsobid-<UPPERCASE_BUILDID>        # NSO ModuleId (file offset 0x40, trailing zeros trimmed)

# free-form title comment

@flag print_values                 # optional: logs each patched value
@flag offset_shift 0x100           # pchtxt offsets are then raw RVAs (see below)

// C-style comments are allowed anywhere
@enabled
<OFFSET_HEX> <BYTES_HEX>           # bytes are in MEMORY ORDER (little-endian per instr)
<OFFSET_HEX> <BYTES_HEX>
@stop
```

Rules that bite you:
- **A blank line resets `@enabled` to off.** Every patch block needs its own
  `@enabled` immediately above its lines. Keep block lines contiguous.
- **Bytes are memory order**, i.e. the little-endian encoding of each 32-bit ARM64
  instruction. `MOVZ X9,#0x780` (word `0xD280F009`) is written `09F080D2`.
- **Offset base.** Ryujinx adds `offset_shift` to each offset, then `MemPatch`
  subtracts the NSO `protectedOffset = 0x100`. So with `@flag offset_shift 0x100`
  set, **the pchtxt offset equals the file RVA** — write RVAs directly, do not add
  0x100 yourself. This is the convention the community retail mods use; match it.
- **RVA from an IDB address**: `RVA = IDB_addr - imagebase`. For these Blitz IDBs
  the image loads at `0x7100000000` (even when the health probe reports
  `imagebase 0x0`), so `RVA = addr - 0x7100000000`. Verify empirically against a
  known instruction before trusting it.
- Filename is arbitrary; Ryujinx matches by `@nsobid` only. Name files
  `<BUILDID>.pchtxt`. `.bak` files are ignored (loader matches `.pchtxt`/`.ips`
  by exact extension).
- **Line endings: CRLF** to match established Switch pchtxt tooling/mods.

## 1. Resolution: the packed scan-buffer constant

Splatoon-family engines expose the render/scan-out size from a Meyers-singleton
getter (`Lp::Sys::ISysInitCstm::getScanBufferSize`, retail `Cstm::SysInit::getScanBufferSize`).
It stores a **packed 64-bit constant `height<<32 | width`** into a global:

```
MOVZ/ORR X9, #<low  half>          ; width  (low 32 bits)
MOVK     X9, #<high half>, LSL#32  ; height (high 32 bits)
STR      X9, [X8]                  ; -> ...getScanBufferSize()::cSize
```

IDA collapses the pair into one line, e.g. `MOV X9, #0x43800000780`
(= 1080<<32 | 1920 = 1920x1080) or `MOV X9, #0x2D000000500` (= 720<<32 | 1280 = 1280x720).

**The compiler picks the encoding and slot order per build — do not assume.**
Observed:
- Retail/QA (1080p): slot0 = `ORR X9,XZR,#0x780` (width), slot1 = `MOVK X9,#0x438,LSL#32` (height).
- March dev (720p):   slot0 = `MOVZ X9,#0x2D0,LSL#32` (height), slot1 = `MOVK X9,#0x500` (width).

### Finding it
1. If the build renders 1080p, search bytes for the height MOVK `?? 87 C0 F2`
   (`MOVK X9,#0x438,LSL#32`). If 720p, search `?? 5A C0 ??` or just find the
   function by symbol.
2. Best: `search_text` for `ScanBuffer` — the demangled getter name pins it
   immediately, then `disasm` the function and read the two-instruction packed MOV
   and its two RVAs. `get_bytes` the 8 bytes to confirm the exact encoding/order
   of each 4-byte slot.

### Scan-out size and render size can be two different constants
Do not assume this constant is *the* resolution. In the oldest Blitz build it drives
only the **scan-out** (the size of the image reaching the display, i.e. what a
screenshot measures), because it is consumed by the layer helpers
(`changeGfxLayerPosSize`, `getScanBufferHalfSize`, `layerScrPosToFullScrPos`), while
the **internal 3D render size** comes from the defaults in the graphics create-arg
constructor (`gsys::SystemTask::CreateArg::CreateArg`) — that build's
`getGsysCreateArg` never writes a size. Later builds copy the scan buffer into that
create-arg field, so one constant covers both; older ones need **both patched**.

The two failure modes are diagnostic, so test with screenshots and read them together:
- screenshot grows, image looks no sharper → you patched the scan-out only (the render
  is still native and being upscaled);
- screenshot stays native → you patched the render only (a sharp frame resolved back
  down into a native-size output).

A quick static check: **count the callers of the wrapper** (`Lp::Utl::getScanBufferSize`).
Zero xrefs does *not* mean the constant is dead — the getter is virtual, so callers
reach it through the vtable. Instead xref the singleton pointer (`ISysInitCstm::spCstm`)
to enumerate everything that pulls sizes off it, and note which of those are layer /
screen-space helpers versus renderer setup.

Constructors like this typically load one `W`-pair (e.g. 1280/720) and `STP` it to
**several** fields — UI canvas, a reference size, and the render size — so you must
change only the render field. With no spare instruction slots, buy them:
- store two adjacent 8-byte fields with a single `STP Xn, Xn, [X0,#off]` after
  packing the pair into one 64-bit register (`MOVZ` + `MOVK ..., LSL#32`);
- fold a vtable load `ADRP + LDR + ADD` into `ADRP + ADD` when the target address is
  statically known.
Then write the new size with `MOVZ Xm,#W` / `MOVK Xm,#H,LSL#32` / `STR Xm,[X0,#off]`.
Verify the scratch registers are dead (re-loaded before their next use) before reusing
them, and validate your `ADRP` encoding by re-deriving an existing one byte-for-byte.

### Patching it (robust rule)
Overwrite **both** 4-byte slots. Requirements: the **first-executed** slot (lower
address) must be a **MOVZ** (it clears the whole register); the second must be a
**MOVK**. Assign each slot the half it already represents:

- If slot0 is the width/low half:  slot0 = `MOVZ X9,#width`,  slot1 = `MOVK X9,#height,LSL#32`.
- If slot0 is the height/high half: slot0 = `MOVZ X9,#height,LSL#32`, slot1 = `MOVK X9,#width`.

Replacing `ORR` with `MOVZ` is fine and often required (many widths — e.g. 2560 =
0xA00 — are not encodable as an ORR bitmask immediate).

## 1b. Unity NX titles: three constants, and a `min()` between them

Unity games are a large share of Switch titles and do **not** use a packed WxH
constant at all — the width and height are separate `MOVZ Wd,#imm` immediates,
repeated at many sites. Recognise the engine from `nn::vi::CreateLayer` +
`nn::oe::GetOperationMode` in one function, `il2cpp` resolver strings
(`sub_X("UnityEngine.Screen::get_width()")`), and a `"Back-Buffers MemoryPool"`
string. Three groups must be patched together:

1. **`ScreenManagerNX` resolution selection** — what becomes `Screen.width` /
   `Screen.height` and the NVN window crop. The shape is always
   `MOVZ Wd,#1280 / MOVZ Wd,#1920 / CSEL` (and 720/1080), gated on
   `GetOperationMode()==1` (docked) and/or `GetPerformanceMode()==1`. There are
   several copies: two in the graphics-init function (selected by a
   resolution-policy global — `CMP W8,#3 / #2 / #1`) and one per notification
   handler (operation-mode changed, performance-mode changed). **Rewrite both
   halves of every pair**, docked *and* handheld: the mod then holds regardless
   of dock state and regardless of which policy branch runs.
2. **`RequestResolution`'s ceiling** — `a1[48]=min(w,1920); a1[49]=min(h,1080)`,
   emitted as `CMP Wn,#0x780 / MOV W8,#0x780 / CSEL W8,Wn,W8,LT`. Patch **only
   the `MOV`** that supplies the ceiling. Leaving the `CMP` at 1920 keeps the
   expression a correct `min()` for every input (`w >= 1920` → the new ceiling,
   `w < 1920` → `w`); patching both would need a re-encoded `CMP` for no gain.
3. **The fixed 1080p allocations.** This is the one that is easy to miss and the
   reason group 1 alone produces a stretched image. The NX player always
   allocates a full 1920x1080 backbuffer `RenderSurface` and 1080p NVN
   back-buffer textures, then renders into a **sub-rect** of them — so the
   allocation caps the true render resolution. Look for a `SetSize2D(1920,1080)`
   on an `nvnTextureBuilder` (typically **three** call sites: colour-storage
   sizing, depth-storage sizing, and the real texture init) plus the
   `CreateRenderSurface`-style vtable call taking `W2=1920, W3=1080`. Watch for
   a shared height register (`MOVZ W25,#0x438` reused via `MOV W2,W25` across two
   builder calls) — verify it is dead before its next assignment.

Memory is usually a non-issue here: the back-buffer pool is sized from
`GetStorageSize` **after** `SetSize2D`, so it grows by itself, and Unity's heap
comes from `nn::os::QueryMemoryInfo` in `nninitStartup` (all remaining memory),
so it follows the emulator's DRAM Size. There is no fixed pool constant to
enlarge — unlike §2b. Budget ≈ `w*h*4*4` bytes for the three colour buffers plus
depth (33 MB at 1080p, 127 MB at 4K).

Two things Unity gives you for free: `Screen.width/height` propagate to
`CanvasScaler`, so the UI scales without a canvas pin (§2c), and there is no
dynamic-resolution ladder (§2d) unless the game itself calls
`Screen.SetResolution` — check by xrefing the
`"UnityEngine.Screen::SetResolution"` resolver string; a reference only from the
icall registration table means the game never calls it.

## 2b. Fixed GPU pools must scale with resolution (or the game aborts)

Changing the render resolution is necessary but **not sufficient**. Engines size
their render buffers from the resolution but size several GPU memory pools from
**hardcoded byte constants** baked once at graphics-system init — these do **not**
scale with resolution. Push the resolution past native and a post-effect's
allocation overflows the pool and the game aborts.

Confirmed case (Blitz): `Cstm::RootTask::getGsysCreateArg` (startup) sets the
render-buffer size from `getScanBufferSize` **but** the dynamic-texture pool from
`Cmn::GfxMgr::getDynamicTextureAllocatorMemSize`, a leaf returning a fixed constant
(`MOV/ORR W0, #<bytes>; RET`) — 64 MB on the 720p protos, 128 MB on the 1080p QA
build. At a from-boot higher resolution, `Cmn::DepthOfField::draw` allocates its
coc/tile buffers at half render-res from `DynamicTextureAllocator::sInstance`,
overflows the fixed pool, and aborts in
`agl::utl::DynamicTextureAllocator::alloc_` with
`"[%s] alloc failed from [%s]. alloc size:%d free size:%d"`.

**Fix:** alongside the resolution patch, enlarge each offending pool constant
proportionally to the pixel ratio `target/native` (keep the engine's built-in
headroom by scaling the *whole* native constant). Overwrite the leaf's
`MOV/ORR W0,#const` with `MOVZ W0,#imm,LSL#16` for pools that are multiples of 64 KiB:

```
MOVZ W0,#imm,LSL#16 : 0x52A00000 | ((imm&0xffff)<<5)   ; value = imm<<16
```
e.g. 144 MB=`0020A152`, 256 MB=`0000A252`, 512 MB=`0000A452`, 576 MB=`0080A452`.
Find these sizers by symbol (`get...MemSize`) or by xref from the gsys/create-arg
builder. Expect **more than one** pool; fix them iteratively as new
`...Allocator::alloc_`/`HaltWithDetail` aborts appear in the log.

**The cascade continues one level up — the parent heap partition.** Enlarging a
pool isn't enough if the pool is carved from a fixed heap partition also sized for
native res. In Blitz the dynamic-texture pool is carved from the **graphics heap**
(`Lp::Sys::HeapGroup` group 1, a.k.a. `mGfxSize`), one of ~5 fixed partitions
(`mSysSize/mGfxSize/mResSize/mSndSize/mSceneSize`) written by a boot initializer as
`MOV Wn, #<bytes>` immediates (find it via xref from `...getAllHeapSize`, or the
initializer that `STP`s into the `HeapInfo` template the singleton getter copies).
If the enlarged pool exceeds `mGfxSize`, boot aborts in
`agl::Initialize → DynamicTextureAllocator::initialize → GPUMemBlockBase::allocBuffer_`
(the requested block > partition). Tell it apart from pool exhaustion by the stack:
`alloc_` = runtime pool full; `initialize`/`allocBuffer_` = boot, partition too small.

Fix by scaling **both** the pool and its parent partition by the same
target/native pixel ratio (preserves the native pool:partition proportion, so the
pool fits with identical headroom). These partitions are `MOVZ Wn,#imm,LSL#16`
values (multiples of 64 KiB); overwrite the immediate. **Check the memory budget:**
sum the partitions (they are fixed byte constants, `getAllHeapSize` returns a
constant, not "remaining") — the total is the app's boot request, and it must stay
under the emulator DRAM (log: `DramSize`) and the NPDM limit. A 4K graphics partition can be ~9× native (e.g. 132 MB → ~1.2 GB). If a *later*
heap create fails, that partition is next in the cascade.

**The last link: the *system* heap, which is consumed as a remainder.** Partitions
that look unrelated to graphics can still be the thing that breaks. In sead,
`TaskMgr::createTaskSync` with a zero `CreateArg::mHeapSize` gives the new task
**all the free space left in its parent heap**, then trims it after `prepare()`.
So every manager task carves out of what remains of `mSysSize`, and the task
created *last* is the one that fails. Symptom: a boot abort far from graphics, e.g.
`seadExpHeap.cpp` `"heap create failed. [<Name>] size: N, parent: <TaskName>,
parent allocatable size: M"` with `M` much smaller than `N`. That means the parent
heap is nearly exhausted, **not** that the failing subsystem is at fault — enlarge
`mSysSize`, not the child. Note `M` in the log: it is the exact headroom you have
left, so it tells you how close the previous resolution tier was to failing.

Enlarging any partition is cheap when the arrangement ends with a
**"take the rest" heap** (Blitz: a final `ExpHeap::create(0, "cOthers", root)`),
because the extra bytes come out of that slack rather than out of another
subsystem. Confirm that shape before being generous.

**Budget convention:** target the default **4 GiB** DRAM as the baseline — size the
enlargements so lower resolutions still fit it. Compute the arrangement total
(sum of the fixed partitions) and compare it against the emulator's application
pool, **not** the DRAM figure: Ryujinx's `KSystemControl.GetApplicationPoolSize`
gives 3285 MB @4 GiB, 4916 MB @6 GiB, 6964 MB @8 GiB, 11060 MB @12 GiB, and the
game's own root heap is smaller still (Blitz reported 6074 MB of the 6964 MB pool,
i.e. ~88%). When a resolution's total exceeds that, **state it in the patch file
header** and name the Ryujinx `System > DRAM Size` the user must select — the
options are **6 / 8 / 12 GiB** (a normal emulator setting, not dev-only). Note the
app may auto-grow its own budget once DRAM ≥ 6 GiB (an `is6GB()`-style check adding
~1 GiB), which eats into the headroom the larger DRAM buys.

## 2c. The 2D/UI virtual canvas is a *separate* size — check it

A game can have a second, independent notion of screen size for its 2D layer: a
**virtual canvas** in which HUD/menu layouts are authored. Getting this wrong is
not a crash, it is the classic "3D scales but the UI sits small in the corner".

In Blitz, `Cstm::RootTask::getGsysCreateArg` writes **two** sizes into the gsys
create arg: the scan buffer (from `getScanBufferSize`) *and*
`Lp::Utl::getVirtualCanvasSize()`. Its implementation differs per build:

- **Later/QA builds:** a hardcoded constant —
  `MOV X9,#0x4434000044A00000; STR X9,[X8]` = two floats `1280.0f, 720.0f`.
  The canvas is pinned to 720p design units no matter what the scan buffer is, so
  the UI scales correctly at any resolution and needs **no patch**.
- **Earlier dev builds:** *derived* — it calls the scan-buffer getter through the
  vtable and `SCVTF`s both halves to float. Raise the scan buffer and the canvas
  grows with it, so 720p-authored layouts occupy only a 1280×720 corner of the frame.

**Fix:** pin the derived getter to the build's **native** resolution (which is what
the later builds hardcode). Overwrite the vtable call + load with immediates:

```
MOVZ W8,#1280 ; 08A08052      (replaces  LDR X8,[X19])
FMOV S0,W8    ; 0001271E      (replaces  LDR X8,[X8,#0x38])
MOVZ W8,#720  ; 085A8052      (replaces  MOV X0,X19)
FMOV S1,W8    ; 0101271E      (replaces  BLR X8)
NOP           ; 1F2003D5      (replaces  LDP S0,S1,[X0])
```
The following `SCVTF S0,S0 / SCVTF S1,S1 / STP S0,S1,[X8]` then cache the pinned
value. Encodings: `MOVZ Wd,#imm` = `0x52800000|(imm<<5)|d`;
`FMOV Sd,Wn` = `0x1E270000|(n<<5)|d`; `NOP` = `0xD503201F`.

Dropping the call is safe here only because the scan-buffer singleton is already
initialized by the caller one line earlier — verify that before removing a call.

## 2d. Dynamic resolution will silently undo your patch

If the render target scales (the engine logs a bigger framebuffer) but the
**screenshot / presented image stays at the native size**, a dynamic-resolution
controller is re-clamping it downstream every frame. This is the failure mode that
looks like "the patch didn't work" even though the log shows it applied.

Detection: count callers of the scan-buffer getter. One caller (the gsys/create-arg
builder) = no dynamic res. **Extra callers are the controller** — in Blitz's QA build
`Lp::Utl::getScanBufferSize` has three, two of them `Cmn::GPUPerfController::calc`
and `::calcForMeasure_`, and the March builds have only the one. It clamps twice:

```c
updateFrameBufferScale_():                       // shrinks the framebuffer
    scale = fullResFlag ? {1,1} : ladder[cur]/ladder[max];
calc():                                          // pins what is presented
    v8 = fullResFlag ? 1.0f : ladder[cur] / (h * scaleY);
    sead::GraphicsNvn::setDisplayBufferWindowCrop(0, 0, w*scaleX*v8, h*scaleY*v8);
```
Because the ladder holds **absolute heights**, `h*scaleY*v8` collapses to
`ladder[cur]` — the output is pinned to e.g. 1080 no matter how large the scan
buffer is. `setDisplayBufferWindowCrop` is what the emulator captures, so that is
the number a screenshot reports.

**Fix — use the controller's own bypass, don't do float surgery.** Both branches are
already gated on one "full resolution" bool member (Blitz: `this+0xD8`). Force every
read of it to 1:
```
LDRB W8,[Xn,#0xD8]   ->   MOVZ W8,#1        ; 0x52800000|(1<<5)|8 = 28008052
```
Patch **all** its read sites (Blitz QA B2: three — two in `calc`, one in
`updateFrameBufferScale_`) or a stale branch still clamps. Measurement/debug-overlay
functions that merely *read* the size (Blitz: `calcForMeasure_`, which prints
`"Resolution %4dp [avg %4dp]"`) need no patch. This also makes an
identity/native-resolution pin genuinely useful: it holds the game at full native
resolution instead of letting it drop under load.

## 3. ARM64 encodings you need (register X9 = Rd 9)

```
MOVZ X9,#imm,LSL#0  : 0xD2800000 | (imm<<5) | 9
MOVZ X9,#imm,LSL#32 : 0xD2C00000 | (imm<<5) | 9
MOVK X9,#imm,LSL#0  : 0xF2800000 | (imm<<5) | 9
MOVK X9,#imm,LSL#32 : 0xF2C00000 | (imm<<5) | 9
```
Write the little-endian bytes of the word. Generator:

```python
def enc(op, imm, lsl, rd=9):
    base = {"movz":0xD2800000, "movk":0xF2800000}[op]
    hw = {0:0,16:1,32:2,48:3}[lsl]
    w = base | (hw<<21) | ((imm & 0xffff)<<5) | rd
    return "".join("%02X"%b for b in w.to_bytes(4,"little"))
```

Common values: width 1920=0x780 2560=0xA00 3840=0xF00; height 1080=0x438 1440=0x5A0 2160=0x870.
(Sanity: `MOVZ X9,#2580` must equal `894281D2`.)

Also used by §2b–§2d: `MOVZ Wd,#imm` = `0x52800000|(imm<<5)|d`;
`MOVZ Wd,#imm,LSL#16` = `0x52A00000|(imm<<5)|d` (value = `imm<<16`);
`FMOV Sd,Wn` = `0x1E270000|(n<<5)|d`; `NOP` = `0xD503201F`.

## 4. Verification checklist (do every time)
1. `get_bytes` the original slots; confirm register, encoding, and slot order.
2. Recompute your replacement words and re-derive the memory-order hex; sanity-check
   one known value against a reference mod.
3. Confirm the `@nsobid` against the NSO ModuleId (file offset 0x40, trailing zeros
   trimmed) — a wrong build id means the patch silently never applies. In a
   Ryujinx run log the tell is whether `IPSwitch:` reports the build-id match.
4. Re-read the written file: contiguous `@enabled` block (comment lines are fine
   between patch lines; a **blank** line ends the block), CRLF, RVA offsets.
5. For any above-native resolution, confirm the matching pool, graphics-heap and
   system-heap patches are present (§2b) or expect an allocator/heap abort.
6. If the build derives its 2D canvas from the scan buffer, confirm the canvas pin
   is present (§2c) — otherwise the UI renders at native size in a corner.
7. Verify end-to-end with an **emulator screenshot**, not by eye: Ryujinx's
   `Window.CaptureFrame` grabs the guest texture at guest dimensions, so the PNG
   size is the true presented resolution. If it still reads native while the log
   shows a larger framebuffer, look for a dynamic-resolution clamp (§2d).
8. Read the crash log's guest `PROGRAM HALT` block before changing anything: it
   names the file, the heap, the requested size and the available size. Let it pick
   the constant to patch instead of guessing.

## 5. Layout
Group by **title ID first** — Ryujinx looks up mods per application ID, so mods for
different builds/regions of the same game must live under their own `<Game> (<TID>)`
folder. Inside that, one mod folder **per resolution**; inside each `exefs/`, one
pchtxt **per build**, named by a human build label (Ryujinx matches on `@nsobid`,
so all builds sharing a title ID coexist and only the matching one applies):
```
<Game> (<TITLEID>)/
  [1920x1080]/exefs/<Build label>.pchtxt   # e.g. "20170328 Proto.pchtxt", "1.1.0 QA B2.pchtxt"
  [2560x1440]/exefs/<Build label>.pchtxt
  [3840x2160]/exefs/<Build label>.pchtxt
  [Level of Detail]/exefs/<Build label>.pchtxt          # switch-lod-bias-pchtxt
  [Shadow Resolution 2048]/exefs/<Build label>.pchtxt   # switch-shadow-resolution-pchtxt
```
**Each offset must be owned by exactly one mod folder.** Two enabled mods writing
the same offset with different values is order-dependent — so the pool/heap
enlargements live only in the resolution mods, and the sibling mods reference them
rather than repeating them.
Title IDs differ **by region**, not by dev-vs-retail (Splatoon 2:
`01003C700009C000` JP, `01003BC0000A0000` global). Builds of the same game can
therefore land in different top-level folders even though the mods are conceptually
the same — check each build's actual application ID (it is in the Ryujinx log:
`ModLoader QueryContentsDir: Searching mods for Application <TID>`) rather than
inferring it from the build's vintage.
Each `[...]` folder is a self-contained, independently-installable mod. A single
resolution pchtxt bundles **all** patches that resolution needs for that build —
the packed WxH change, the UI canvas pin (§2c), and every pool/heap enlargement
(§2b) — under one `@enabled` block. Resolution mods above native are for emulator supersampling (real
hardware caps at 1080p docked). A resolution equal to native (e.g. 1080p on an
already-1080p build) is an identity/anti-dynamic-res pin needing no pool change —
note that in the file. Header/description wording and a repo-URL footer are the
author's; preserve them across edits.
