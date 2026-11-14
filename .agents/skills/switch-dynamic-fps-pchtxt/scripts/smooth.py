"""Fraction of updates in which the player position changes while the left stick is held (HWDE 1.0.1 addresses: update counter main+0xBE20EC, player *(*(main+0xC34DD8)+2824)+0xBA0). Adapt the addresses per game. usage: smooth.py [sec]"""
import struct, sys, time
sys.path.insert(0, '/home/judas/.cache/sbb')
import sbb
s = sbb.connect()
def q(addr): return struct.unpack('<Q', bytes.fromhex(sbb.send(s, f"peekAbsolute 0x{addr:X} 8").decode().strip()))[0]
def qm(off): return struct.unpack('<Q', bytes.fromhex(sbb.send(s, f"peekMain 0x{off:X} 8").decode().strip()))[0]
p = q(qm(0xC34DD8) + 2824) + 0xBA0
base = int(sbb.send(s, "getMainNsoBase").decode().strip(), 16)
sec = float(sys.argv[1]) if len(sys.argv) > 1 else 2
sbb.send(s, "setStick LEFT 0 -32000"); time.sleep(0.5)
seen = {}
t = time.time()
while time.time() - t < sec:
    r = bytes.fromhex(sbb.send(s, f"peekAbsoluteMulti 0x{base + 0xBE20EC:X} 4 0x{p:X} 12").decode().strip())
    u = struct.unpack('<I', r[:4])[0]; seen.setdefault(u, r[4:])
sbb.send(s, "setStick LEFT 0 0")
us = sorted(seen); ch = sum(1 for a, b in zip(us, us[1:]) if b == a + 1 and seen[a] != seen[b]); pairs = sum(1 for a, b in zip(us, us[1:]) if b == a + 1)
print(f"sampled {len(us)} updates, consecutive pairs {pairs}, position changed in {ch} ({100*ch/max(pairs,1):.0f}%)")
