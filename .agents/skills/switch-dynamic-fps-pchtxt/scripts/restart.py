"""Restart the game and apply {off,new,old} records (hex, offsets relative to main) as soon as main is mapped.

usage: restart.py [recs.json ...]. A running loop keeps its old translated code, so code patches must land before it starts.
The old process keeps answering getMainNsoBase for ~0.1 s after restartGame (often with the same base), so a base is
only accepted after the server has gone down once; every record is read back to prove it landed in the new process."""
import json, sys, time
sys.path.insert(0, '/home/judas/.cache/sbb')
import sbb
s = sbb.connect()
sbb.send(s, "restartGame")
s.close()
t0 = time.time()
went_down = False
while True:
    time.sleep(0.02)
    try:
        s = sbb.connect()
        r = sbb.send(s, "getMainNsoBase")
        base = int(r.decode().strip() or '0', 16)
        if base and went_down:
            break
        if not base:
            went_down = True
        s.close()
    except Exception:
        went_down = True
    if time.time() - t0 > 120:
        sys.exit('timeout')
recs = []
for p in sys.argv[1:]:
    recs += json.load(open(p))
for r in recs:
    sbb.send(s, f"pokeMain 0x{r['off']:X} 0x{r['new']}")
bad = [r for r in recs if sbb.send(s, f"peekMain 0x{r['off']:X} {len(r['new']) // 2}").decode().strip().lower() != r['new'].lower()]
print(f"restarted, {len(recs) - len(bad)}/{len(recs)} records applied after {time.time() - t0:.1f}s")
if bad:
    sys.exit(f"not applied: {', '.join(hex(r['off']) for r in bad)}")
