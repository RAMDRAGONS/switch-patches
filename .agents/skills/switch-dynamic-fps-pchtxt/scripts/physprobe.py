"""Per-update physics probe: jump peak and air time, or steady run speed, sampled once per game update.

usage: physprobe.py jump|run|traj FRAME TIME POS [hold_s]
  FRAME  main offset of a u32 that increments once per update (dedupes samples)
  TIME   pointer chain to the f32 game-time accumulator (seconds), POS chain to the actor's f32 x (y at +16)
  chain syntax: start at main+OFF; each '>N' reads the u64 at (current + N); a trailing '+N' adds N. A GOT slot
  needs two hops to reach the object (slot -> variable -> object).
  e.g. Metroid Dread 2.1.0: physprobe.py jump 0x1D47390 'main+0x1CBA0E8>0>0+0x2C' 'main+0x1CBA088>0>0>0x29B8>0x10+0x44'
jump presses B (edit BUTTON), run holds the left stick right then left. Compare the printed numbers across
pace.cs refresh rates: speed should match; a jump peak that grows with the rate is semi-implicit Euler."""
import struct, sys, time
sys.path.insert(0, '/home/judas/.cache/sbb')
import sbb

BUTTON = 'B'
s = sbb.connect()
BASE = int(sbb.send(s, "getMainNsoBase").decode().strip(), 16)


def rd(addr, n): return bytes.fromhex(sbb.send(s, f"peekAbsolute 0x{addr:X} {n}").decode().strip())


def resolve(chain):
    head, *hops = chain.split('>')
    addr = BASE + int(head.split('+')[1], 16)
    for h in hops:
        off, _, add = h.partition('+')
        addr = struct.unpack('<Q', rd(addr + int(off, 16), 8))[0] + (int(add, 16) if add else 0)
    return addr


mode, frame, tchain, pchain = sys.argv[1:5]
hold = float(sys.argv[5]) if len(sys.argv) > 5 else 0.5
fa, ta, pa = BASE + int(frame, 16), resolve(tchain), resolve(pchain)
seen = {}


def run_for(d):
    end = time.time() + d
    while time.time() < end:
        r = bytes.fromhex(sbb.send(s, f"peekAbsoluteMulti 0x{fa:X} 4 0x{ta:X} 4 0x{pa:X} 4 0x{pa + 16:X} 4").decode().strip())
        f = struct.unpack('<Ifff', r)
        seen.setdefault(f[0], f)


if mode == 'run':
    sbb.send(s, "setStick LEFT 32000 0"); run_for(hold); sbb.send(s, "setStick LEFT -32000 0"); run_for(hold)
    sbb.send(s, "setStick LEFT 0 0"); run_for(0.3)
else:
    sbb.send(s, f"press {BUTTON}"); run_for(hold); sbb.send(s, f"release {BUTTON}"); run_for(1.2)
rows = [seen[k] for k in sorted(seen)]
span = rows[-1][1] - rows[0][1]
print(f"{mode}: {len(rows) - 1} updates in {span:.2f} game s ({(len(rows) - 1) / max(span, 1e-6):.0f}/s)")
if mode == 'run':
    best = 0
    for i, a in enumerate(rows):
        b = next((r for r in rows[i + 1:] if r[1] - a[1] >= 0.2), None)
        if b: best = max(best, abs(b[2] - a[2]) / (b[1] - a[1]))
    print(f"steady speed {best:.0f} units/s (max over 0.2 s windows)")
else:
    y0 = rows[0][3]
    peak = max(rows, key=lambda r: r[3])
    up = next((r for r in rows if r[3] > y0 + 0.5), None)
    down = next((r for r in rows if up and r[1] > peak[1] and r[3] <= y0 + 0.5), None)
    print(f"peak {peak[3] - y0:.1f} at {peak[1] - up[1]:.3f} s, landing {down[1] - up[1]:.3f} s" if up and down else "no complete arc")
    if mode == 'traj':
        for a, b in zip(rows, rows[1:]):
            print(f"{b[1] - rows[0][1]:7.4f} y={b[3] - y0:8.2f} vy={(b[3] - a[3]) / max(b[1] - a[1], 1e-6):8.1f}")
