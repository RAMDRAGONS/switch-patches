---
name: switch-framerate-pchtxt
description: >-
  Author Nintendo Switch frame-rate exefs pchtxt mods by finding what actually
  paces the engine's frames in IDA — a vsync-event wait, an NVN present interval,
  or a sleep-based limiter — and rewriting it to a target rate. Use when asked for
  a "60 FPS mod", "144 FPS patch", "unlock framerate", or any pchtxt that changes
  how often a Switch title presents.
---

# Switch frame-rate pchtxt mods

Sibling skills, each its own mod folder: `switch-resolution-pchtxt`,
`switch-lod-bias-pchtxt`, `switch-shadow-resolution-pchtxt`. Same rules apply —
deliver as pchtxt only, never modify the dump, open IDBs **in place**, CRLF line
endings, and see §0 of `switch-resolution-pchtxt` for the pchtxt format itself
(`@nsobid`, `@flag offset_shift 0x100` so offsets are raw RVAs, blank lines
resetting `@enabled`).

## 1. Find the pacer before you look for a number

The instinct is to search for the constant `60`. Usually there isn't one. Frame
rate is a **consequence** of whatever the frame loop blocks on, so identify the
blocking mechanism first. On Switch there are only a few:

- **Vsync-event pacing.** A dedicated thread does
  `nn::os::WaitSystemEvent(<vi display vsync event>)` in a loop and publishes a
  timestamp; the render thread blocks until that timestamp advances. Find it by
  xrefing `nn::vi::GetDisplayVsyncEvent` to the event object, then xrefing the
  event. Rate = vsync rate.
- **The graphics present interval.** `nvnWindowSetPresentInterval` /
  `nvnWindowBuilderSetPresentInterval` (or the `eglSwapInterval` equivalent).
  Rate = vsync rate ÷ interval. Locate the entry point by xrefing the literal
  `"nvnWindowSetPresentInterval"` — NVN is loaded by name through
  `nvnDeviceGetProcAddress`, so the string leads to the global holding the
  pointer, and xrefing *that* global gives the engine's setter.
- **A sleep/spin limiter.** The loop computes a deadline from a target-FPS
  number and sleeps. This is the only shape with an actual number to patch, and
  it is the *rarest* on Switch because the display is fixed at 60 Hz.
- **Buffer-queue backpressure.** Even with none of the above, N swapchain
  buffers plus a semaphore acquired per frame and released per present caps you
  at the compositor's consumption rate.

Read the engine's own vocabulary: a `SetSyncInterval(int)` that does
`interval = max(interval, 1)` is telling you 60 FPS is a hard ceiling by
construction, and that no amount of searching will turn up a "60" to edit.

## 2. Rewriting a vsync wait into a fixed-period sleep

When the engine is vsync-paced there is no number, so **manufacture one**: turn
the pacing thread into a fixed-period thread by replacing its blocking wait with
`nn::os::SleepThread(nanoseconds)`.

The wait site is nearly always shaped like this, which is exactly the three
instruction slots you need:

```
ADRP Xn, <event>@PAGE      \  IDA renders these two as one "ADRL Xn, event"
ADD  Xn, Xn, #<event>@OFF  /  line — they are 8 bytes, two patchable slots
...
MOV  X0, Xn
BL   nn::os::WaitSystemEvent
```

Rewrite the address materialisation into an immediate and retarget the call:

```
MOVZ Xn, #<ns & 0xFFFF>            ; 0xD2800000 | (imm<<5) | n
MOVK Xn, #<ns >> 16>, LSL#16       ; 0xF2A00000 | (imm<<5) | n
BL   nn::os::SleepThread           ; 0x94000000 | (((dst-src)>>2) & 0x03FFFFFF)
```

`nn::TimeSpan` is a plain nanosecond `int64` in X0, so the same register the
event pointer used carries the period. Frame period = `1e9 / target_fps`.

Two things to verify before you commit to this:
- **The scratch register is dead after the call.** Check every use of `Xn`
  through the rest of the loop — in a pacing thread it is typically loaded once
  in the prologue and used only as the wait argument.
- **Your `BL` encoder is right.** Re-derive the *original* call's bytes with the
  same function and compare — if `bl(site, WaitSystemEvent)` doesn't reproduce
  the bytes already there, do not trust `bl(site, SleepThread)`.

Sleeping on a dedicated thread is what makes this accurate: the period is the
sleep alone, not sleep + frame work, so the tick rate doesn't drift with load.
Never put the sleep on the render thread for this reason.

## 3. Pacing alone is not enough — unblock presentation too

Raising the tick rate does nothing if presenting still blocks on the display.
Force the present interval to 0 as well, at the **builder** call that configures
the window at creation (`nvnWindowBuilderSetPresentInterval(builder, interval)`):
patch the argument load to `MOV W1, WZR` (`0x2A1F03E1`).

Then look for a **readback** — engines commonly do
`interval = nvnWindowGetPresentInterval(window)` right after creating the window
and cache it. That readback will observe your 0 and can flip the engine onto a
different code path. In the Unity NX player the cached interval selects between
two pacing schemes:

- `interval != 0` → the vsync thread publishes the tick (the path you just
  turned into your limiter);
- `interval == 0` → **presenting** publishes the tick, so the frame wait returns
  immediately and the rate is uncapped.

So `NOP` the readback store and let the cached value stay non-zero: the NVN
window runs unsynchronised while the engine still uses its vsync-thread path.
Finally, neutralise the runtime setter (`SetSyncInterval` → `RET`, `0xD65F03C0`)
so a later `vSyncCount` change cannot reinstate a blocking interval.

That combination — sleep-paced tick, interval 0, readback dropped, setter
disabled — is a complete, self-contained frame-rate mod.

## 4. Emulator-side alternative, and why to prefer the mod

Ryujinx's `VSyncMode.Custom` sets `TargetVSyncInterval`, and `SurfaceFlinger`
signals the guest vsync at exactly that rate (`_ticksPerFrame` derives from it).
For a purely vsync-paced engine this alone changes the frame rate with **no
patch at all** — worth knowing, and worth telling the user.

Prefer the mod anyway when you have been asked for specific rates: it makes the
rate a property of the mod rather than of the emulator's configuration, and it
keeps behaviour identical across VSync modes. Note the interaction: when the
guest's swap interval is 0, Ryujinx composes once per queued buffer
(`_nextFrameEvent` is set on `BufferQueued`) rather than on a timer, so the
presented rate follows the guest — which is what makes §3 work regardless of the
emulator's VSync setting.

## 5. What to check before shipping a rate above native

- **Fixed-timestep simulation.** If gameplay advances a constant amount per
  frame instead of by delta time, the whole game speeds up proportionally. Check
  that the frame-wait function's **return value** is a real measured elapsed
  time (e.g. `ConvertToTimeSpan(now - start)`) and that it feeds delta time. In
  Unity this is safe by construction; in bespoke engines it often is not.
- **Audio-synced gameplay.** Rhythm games key note timing to the audio clock,
  which is unaffected — but input is polled per frame, so hit-window *feel*
  changes even when timing is technically identical. Say so.
- **Animation and physics.** `Time.fixedDeltaTime`-style fixed steps decouple
  physics; frame-driven animation does not.
- **GPU headroom.** Pairing a frame-rate mod with a resolution mod multiplies
  the cost. State the combination in the file header.

## 6. Verification
1. Re-derive every rewritten instruction's original bytes with your encoder and
   compare against `get_bytes` — especially any `BL` (§2).
2. Confirm the target of a retargeted call is a real, *used* PLT stub: xref it
   and check other code already calls it, which proves the relocation resolves.
3. Measure with the emulator's FPS readout, not by eye, and check it holds in
   both menus and gameplay — a rate that is right in one and wrong in the other
   means you patched one of two pacing paths.
4. Confirm the game still runs at the *stock* rate with the mod disabled, so you
   know the number you measured came from the patch.

## 7. Layout
One mod folder per rate, following the shared convention:
```
<Game> (<TITLEID>)/
  [75 FPS]/exefs/<Build label>.pchtxt
  [144 FPS]/exefs/<Build label>.pchtxt
```
**Each offset is owned by exactly one mod folder**, and the rates are mutually
exclusive by nature — never ship a frame-rate offset inside a resolution mod, or
two enabled mods will write the same offset and the result is order-dependent.
