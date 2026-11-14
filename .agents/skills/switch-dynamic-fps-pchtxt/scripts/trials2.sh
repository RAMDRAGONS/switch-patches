#!/bin/bash
# trials2.sh <n> <label> <recs.json>...: boot n times with the records at ${HZ:-120} Hz, press A once,
# and classify a screenshot region against a known-good reference ($REF, crop box $BOX) as ok or LOCKED.
# Run from the directory holding the records; restart.py, pace.cs and sbb.py come from this skill / ~/.cache/sbb.
here=$(dirname "$(readlink -f "$0")")
n=$1; label=$2; shift 2
for i in $(seq 1 $n); do
  python "$here/restart.py" "$@" >/dev/null && sleep ${BOOT:-22}
  python ~/.claude/skills/driving-ryujinx-botbase/scripts/run.py "$here/pace.cs" hz=${HZ:-120} >/dev/null
  python ~/.cache/sbb/sbb.py seq "click A" "sleep 4" "shot /tmp/trial.png" >/dev/null
  python -I -c "
from PIL import Image, ImageChops, ImageStat
box = tuple(int(v) for v in '${BOX:-20,70,280,300}'.split(','))
a = Image.open('/tmp/trial.png').convert('L').resize((640, 360)).crop(box)
b = Image.open('${REF:?set REF to a known-good screenshot}').convert('L').resize((640, 360)).crop(box)
d = ImageStat.Stat(ImageChops.difference(a, b)).mean[0]
print('$label', $i, 'ok' if d < 12 else 'LOCKED', round(d, 1), flush=True)"
done
