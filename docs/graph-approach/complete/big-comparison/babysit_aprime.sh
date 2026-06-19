#!/usr/bin/env bash
RID=$(cat /tmp/aprime_rid)
cd /Users/peter/code/task-world
resumes=0; laststate=""
for i in $(seq 1 50); do
  S=$(curl -s --max-time 5 http://localhost:8000/api/runs/$RID)
  status=$(echo "$S" | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])" 2>/dev/null)
  pause=$(echo "$S" | python3 -c "import sys,json;print(json.load(sys.stdin).get('pause_reason') or '-')" 2>/dev/null)
  nodes=$(curl -s --max-time 5 "http://localhost:8000/api/runs/$RID/graph" | python3 -c "import sys,json;d=json.load(sys.stdin);ns=d['node_states'];print(sum(1 for v in ns.values() if v=='completed'),'/',len(ns),'completed; running=',[k for k,v in ns.items() if v=='running'])" 2>/dev/null)
  af=$(ps -p 99872 >/dev/null 2>&1 && echo RUN || echo DONE)
  echo "$(date +%H:%M:%S) A'=$status/$pause  nodes=$nodes  armA_finish=$af" >> metrics/aprime.log
  if [ "$status" = "completed" ] || [ "$status" = "failed" ]; then echo "A_PRIME_TERMINAL=$status" >> metrics/aprime.log; break; fi
  if [ "$status" = "paused" ] && [ "$pause" = "graph_blocked" ]; then
    if [ "$nodes" = "$laststate" ]; then resumes=$((resumes+1)); else resumes=0; fi
    laststate="$nodes"
    if [ $resumes -ge 6 ]; then echo "A_PRIME_STUCK no progress after 6 resumes" >> metrics/aprime.log; break; fi
    uv run orchestrator runs resume $RID >/dev/null 2>&1
    echo "  -> resumed ($resumes)" >> metrics/aprime.log
  fi
  sleep 45
done
echo "BABYSIT_DONE" >> metrics/aprime.log
