import sys
from driver_common import run_codex, arm_totals
arm = sys.argv[1]; role = sys.argv[2]; armdir = sys.argv[3]
prompt = sys.stdin.read()
run_codex(arm, role, prompt, armdir, sandbox="workspace-write", timeout=2400)
print("TOTALS", arm_totals(arm))
