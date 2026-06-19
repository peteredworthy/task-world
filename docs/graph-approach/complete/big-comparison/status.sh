#!/usr/bin/env bash
# Compact status of all four arms.
cd /Users/peter/code/task-world/docs/graph-approach/big-comparison
for p in "A:86047" "B:85634" "C:86048"; do
  name="${p%%:*}"; pid="${p##*:}"
  if ps -p "$pid" >/dev/null 2>&1; then st="RUNNING"; else st="DONE"; fi
  echo "Arm $name (pid $pid): $st"
done
echo "--- last lines per arm runner ---"
for f in armA armB armC; do echo "[$f] $(tail -1 metrics/${f}_run.out 2>/dev/null)"; done
echo "--- A' real graph run ---"
curl -s --max-time 5 http://localhost:8000/api/runs/c095d96e-b614-4ad0-a8b1-9aaec61bd97b | \
  python3 -c "import sys,json;d=json.load(sys.stdin);print('status:',d['status'],'pause:',d.get('pause_reason'),'err:',str(d.get('last_error'))[:80])" 2>/dev/null
echo "--- arm main.py sizes ---"
for a in arm-a arm-b arm-c; do echo "$a: $(wc -l < /Users/peter/code/comparison-arms/$a/main.py 2>/dev/null) lines main.py"; done
echo "--- codex procs live ---"; pgrep -fc "codex exec" 2>/dev/null
