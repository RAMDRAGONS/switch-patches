---
name: switch-dynamic-fps-pchtxt
description: >-
  Author Nintendo Switch "dynamic" or "uncapped" frame-rate exefs pchtxt mods,
  where the game measures each frame's real time and steps by it instead of a
  fixed 1/30 or 1/60, so it keeps real-time speed at whatever rate the emulator
  refresh allows. Use when asked for a "dynamic FPS", "uncapped FPS", "unlocked
  FPS", "120/240 FPS dynamic" or "delta time" mod, or to fix a game that speeds
  up or stalls above 60 FPS (Ryujinx / Atmosphere).
---

# Switch dynamic / uncapped FPS pchtxt mods

Sibling of `switch-framerate-pchtxt`, which covers fixed-rate mods (find the
pacer, set a rate). A dynamic mod goes further: every update measures the real
frame time and feeds it to the engine's own time variables, so speed stays
correct at 40, 60, 120 or 240 FPS. Same rules as the siblings: pchtxt only, open
IDBs in place, CRLF, the pchtxt format in `switch-resolution-pchtxt` §0. Use the
IDA MCP helper skills (`using-ida-mcp`, `analyzing-switch-arm64-in-ida`,
`writing-switch-pchtxt`) and test live with `driving-ryujinx-botbase`.

## 0. What "dynamic" means here

- **Keep the game's swap interval.** Don't set interval 0. The emulator's
  refresh (Ryujinx custom refresh rate or unbounded) is the cap; on hardware the
  mod still runs at 60. Third-party mods (Fl4sh's `v2.pchtxt` files) set an SDK
  present interval of 0 to uncap; that is a separate, optional choice.
- **Remove only the game's own limiter** (sleep-until-deadline, or waits counted
  in vsyncs) and replace it with the clock below.
- **Every time quantity the engine reads must come from the measured time.**
  Missing one leaves a system that runs too fast, too slow, or stalls.
- **First check whether it is already dynamic.** Raise the refresh
  (`pace.cs hz=120`), read `fps.cs`, and read the engine's timer object live.
  Metroid Dread already measured every frame (dt = real µs × timescale, clamped
  to 0.1 s), presented with interval 1 and spun only until 1 ms had passed: it
  ran 120 FPS with dt 8.3 ms unmodified. Then skip §3/§4b and go to §5b, the
  audit, which is the whole job.

## 1. Map every loop that advances the game

Games often have more than one frame loop, and a clock hooked into one of them
silently does nothing in the others:

- a **step thread** with the limiter (gameplay),
- a **single-thread loop** that updates and presents in one iteration, paced only
  by present (menus, loading); it can run a render path several times per
  update or spin fast while the step thread owns gameplay,
- a **movie player** with its own present interval (pre-rendered video; leave
  it at its rate).

Find them statically (callers of the scene update, thread names passed to the
thread-create wrapper, e.g. `"FrameStepLoop"`), then confirm live which one runs
in each scene by walking guest thread stacks (§6, `threads.cs`). Hook the clock
so it runs **exactly once per update in every loop**. Check with a counter the
clock increments: calls per second must equal the guest frame rate in menus,
loading and gameplay. A hook on a loop head that a render-only loop also passes
through fires hundreds of times per second; two hooks on calls that both run in
one iteration double it.

## 2. Inventory the engine's time variables

Read the step setter and every global it writes, then classify each reader.
Typical set (Koei Tecmo KTGL, Hyrule Warriors DE):

| Kind | Example | Dynamic value |
|---|---|---|
| Integer tick step (60 Hz ticks per update, 1 or 2) | 346 readers; loops `for i < step`, `timer -= step` | whole ticks from an accumulator |
| Same step converted to float (`LDR` + `UCVTF`) | 215 of those 346 | the fractional frames `r` |
| Float frame ratio for UI / layouts | `layout->update(frames)` | `r` |
| Lag factor (real time / tick, ≥1 at stock) | multiplies into a timescale | 1.0, or drop it: `r` already contains the lag |
| Target fps float, read as `1/fps` seconds | `1.0 / fps` | `60 / r` |
| Requested step from scenes (cutscene asks 2) | saved and restored by events | record it, don't apply it |

Look for **double counting**: a product like `timescale × step` where the
timescale already contains the measured lag gives `r²`. Remove the lag term from
the product rather than special-casing the readers.

## 3. The clock

Once per update:

```
r    = (now - last) * 60 / tick_freq      ; frames of 1/60 s (tick_freq 19.2 MHz)
r    = clamp(r, r_min, r_max)             ; r_max 2 keeps stock's worst case (step 2)
acc += r
step = min(floor(acc), stock_step)        ; integer tick step: 0 or 1 in gameplay
acc  = min(acc - step, 1)                 ; drop the excess, never build a backlog
fstep = r; fps = 60 / r                   ; float users, fps users
```

- `r_max = 2`: below 30 FPS the float users slow down instead of taking larger
  steps than the game was ever tested with.
- **Never hand integer users a step stock never produces in that context.**
  Without the `min`, HWDE's main menu never showed its buttons in about a third
  of boots at 120 Hz: load hitches let the accumulator emit step 2 in menus,
  where stock only ever steps by 1 (likely a counter tested with `==` jumping
  past its target). Holding the integer step at 1 or capping it fixed it
  (0 of 12 boots). Below 60 FPS the integer
  systems then slow down exactly as stock does under lag, while float users stay
  real-time.
- `r_min` only guards against nonsense; with `FMOV` immediates the smallest is
  0.125 (480 FPS).
- Keep `last` and `acc` in memory nobody else touches: alignment padding next to
  the step globals (check `rw()` is empty), or the zero-filled tail of the last
  `.bss` page (Ryujinx maps it; verify zeros live with `peekMain`).
- The limiter body itself is the natural code cave once the limiter is gone;
  shrink the setter to its one surviving store and reuse the rest.

## 4. Integer-tick engines

If most logic counts whole ticks, `step` is often 0 above 60 FPS:

- Code that says `if (step != 0)` or loops `step` times is fine.
- `max(step, 1)` clamps (frame counters, ring-buffer slots) advance on zero-tick
  updates and run fast: make them advance by `step`.
- `60 / step` divisions return 0 on ARM for step 0: check what the 0 does.
- `(int)(step_float × x)` truncations lose fractions: keep the integer step there.
- Systems driven only by integer ticks stay at 60 Hz motion above 60 FPS but at
  the correct speed. Only float readers get smoother.
- **Code that ignores the step entirely** (decrements per update) runs N times
  too fast at N×60 FPS. These have to be found one by one, live (§6).
- **Measure smoothness, not just speed.** Poll an object's position together
  with the update counter: if it changes on only half the updates at 120 Hz,
  that object moves in whole ticks. When characters tick but the camera uses the
  float step, characters visibly jitter against the camera above 60 FPS. That
  can't be fixed by adjusting the step; it takes render-side interpolation
  (previous and current tick transforms blended by the accumulator fraction) or
  keeping the camera on ticks too.

## 4b. Pace the step thread once the limiter is gone

A sleep limiter often was the only thing pacing a separate update thread. With it
removed, HWDE's step thread ran about 770 updates/s against 120 presents. Wait
for the graphics present counter to change before each update (with a timeout
so a stalled present can't hang the game): one update per presented frame, and
update N+1 still overlaps the render of N. Find the counter in the present
function (`frame number += 1` next to the NVN present call).

## 5. Patching float readers in bulk

For each `LDR Wn/Sn, [Xb]` of the integer step followed by `UCVTF Sd, Sn`:

- if `Xb` still holds the global's address at the `UCVTF`, replace the `UCVTF`
  with `LDR Sd, [Xb, #off]` of the float step (place the float step at a small
  positive offset from the integer step so one immediate reaches it);
- if the load clobbered its own base (`LDR W8, [X8]`), rewrite the load into the
  float load and NOP the `UCVTF`, but only when `Wn` has no other use;
- check what the converted value feeds: truncations back to int, products with
  another time factor (double counting), equality tests.

Script the classification over all sites; hand-review the rejects.

## 5b. Auditing an engine that already steps by measured time

Most of the code is right; the job is finding what isn't. Measure first, then
search by pattern (Metroid Dread 2.1.0 is the worked example):

1. **Invariants across rates.** `physprobe.py` at 30/60/120/240: run speed,
   jump peak, landing time. Equal speeds and a peak that grows with the rate
   (Dread: 371 / 385.5 / 392.6 / 394.8) is semi-implicit Euler: forces go into
   velocity, then position moves by velocity × dt, so the peak is
   v0²/2g − v0·dt/2. The `traj` mode shows dv per update = g·dt exactly.
2. **Readers of the nominal frame time.** Find the getter for 1/fps (or the fps
   field) and list every caller. Code that replaces the dt it was handed with
   1/fps advances a fixed 1/60 per update. Dread's in-game and main-menu GUI roots
   did that (2× fast at 120); others only convert seconds to frames, set a
   one-frame deadline or clamp, which are fine. Replace with the **real** frame
   time, not the game dt: dt carries the game timescale (pause, slow motion),
   which is why the menus avoided it.
3. **Per-update fractions.** `x += rest × 0.2` per update finishes 2× sooner at
   120. Replace the constant with `k × dt` (0.2 → 12·dt) when the code already
   trims overshoot; check remaps such as `a + (1−a)·0.02` of a time value, which
   don't accumulate and are fine. `v *= f` per update needs `f^(60·dt)`; note
   it if there is no room for `powf`.
4. **Frame-number readers** are usually once-per-frame guards
   (`if (last != frame) { last = frame; ... }`), fine at any rate.
5. **Names lie.** Strings next to a constructor (`DebugIngameMenu`) did not make
   the class debug-only: the `IngameMenuRoot` built beside it was the live UI
   root. Enumerate the live instances (GUI root list, entity tables) before
   writing code off as dead.

### Making Euler integration match 60 FPS

Stock 60 FPS equals exact motion plus `F·t·(H − t)/2` of extra displacement
per update (t = this update's dt, H = the stock step, 1/60). Adding that term
makes every rate reproduce the 60 FPS arc (Dread after the fix: 385.4 to 385.6 at
30 to 240, landing within one frame). Where to add it:

- **At the displacement the collision move consumes**, not at an earlier
  predicted transform. Dread's `sub_978C24` computed `x + v·t + ½F·t²` into a
  matrix that the sweep then overwrote; a ×200 correction there changed nothing.
  **Exaggerate a new hook ×100 before tuning it**: no effect means the wrong
  site.
- **Moving the force clear is unsafe**: the mover may also add F·t to velocity,
  callers pass read-only zero vectors, and actors that skip the move a frame
  accumulate forces (geometric growth above 2× the base rate).
- **Pass data between the two sites through a tagged global**: the force
  integrator stores `{actor, F/2}` in an unused `.bss` tail; the mover applies it
  only when the tag equals its own actor, then clears it. A mismatch degrades to
  stock behaviour instead of corrupting anything.
- **Skip axes sitting at a velocity clamp** (terminal fall speed): there stock
  has no Euler error and the correction would speed the fall up.
- Use the engine's own 1/fps for H: cutscenes that stock runs at 30 then keep
  their 1/30 arcs.

### Room for caves

When nothing in `.text` is provably dead, shrink code you are already in:
word-by-word struct copies (`LDUR W8 / STR W8` × 16) become two `LDP/STP Q`
pairs (32 instructions → 8, Q16 to Q31 are caller-saved), and `FMUL + FADD` pairs
become `FMADD`. Check every replaced range for branch targets
(`XrefsTo` per word) and keep register state at the exit identical.

## 6. Live testing (botbase)

Scripts in `scripts/` (run `.cs` files with the botbase skill's `run.py`):
`restart.py` (restart and poke records early), `pace.cs hz=<N|unbounded|restore>`,
`fps.cs` (guest FPS), `threads.cs base=<main base>` (guest stacks into main),
`trials2.sh` (repeated boots with lock detection), `physprobe.py` (per-update
jump/run/trajectory measurements from pointer chains), `smooth.py` (per-update
motion check; HWDE addresses, adapt per game).

- **Pokes don't reach running loops.** A loop's translated code stays linked to
  its old callees, so a poked limiter never runs. Restart (`restartGame`) and
  poke within about a second of `getMainNsoBase` answering. Pokes into functions
  that are called every frame (integrators, movers) do take effect live: pause
  the game (open the map) while writing multi-word blocks.
- **The old process answers for ~0.1 s after `restartGame`**, with the same
  base, so pokes sent then are lost on reload. `restart.py` waits for the server
  to go down once and reads every record back.
- **Don't overwrite the user's save**: save stations prompt; answer B.
- **Guest FPS** is `ctx.Device.Statistics.GetGameFrameRate()`.
  `DebugHooks.FramePresented` fires on every host vsync and over-counts.
- **Refresh rate**: `ctx.Device.SetRefreshRate(hz, unbounded)`; a restart
  resets it, set it after each boot. Without raising it the game can't exceed 60.
- **Which loop runs**: walk each guest thread's frame-pointer chain from
  `Context.GetX(29)` with the process `CpuMemory` and print return addresses
  inside main.
- **Random lockups** at high refresh: boot N times and classify a screenshot
  region against a known-good reference; compare against stock at the same
  refresh before blaming the mod, then bisect by variant (float step held
  constant vs integer step held constant). At a 30% failure rate, 6 clean boots
  still happen by chance about 1 time in 8, so bisecting reader subsets is slow;
  diffing `.data`/`.bss` and the scene objects between a locked and two good
  boots (keep only fields equal in both good runs) narrows it much faster.
- Watch the clock globals with `peekMain` and an update counter to get updates
  per second.

## 7. Reference mods

Fl4sh's packs in `~/Documents/Git/Switch-Emulator-Ultrawide-FPS-Mods/` (zips;
extract into `~/.cache`): Metroid Prime Remastered `[Unlocked FPS Dynamic]`
measures ticks per frame, smooths with an EMA (0.15 new / 0.85 old) and feeds the
engine's delta time; its 120/240 variants differ only in a tick-based limiter
target (160000 / 80000 ticks). Their `v2.pchtxt` files patch an SDK module's
present interval. None of them document their sites; use them for the shape of
a solution, not offsets. Their Metroid Dread pack only sets the NVN present
interval at init (1000/2000) and disables the audio-synced cutscene path; it
fixes none of the dt-dependent behaviour in §5b.

Shipped example: `Metroid Dread (010093801237C000)/[Dynamic Uncapped FPS]`
(cutscene interval and timer, menu roots on real time, a per-update push made
dt-based, and the Euler correction with its full assembly source in the header).
