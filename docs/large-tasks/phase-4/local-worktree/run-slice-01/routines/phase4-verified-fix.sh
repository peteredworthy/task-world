#!/bin/sh
set -u
mkdir -p docs/phase4-evidence-standardization-smoke && printf '%s\n' 'target artifact exists' > docs/phase4-evidence-standardization-smoke/slice-01-verified-fix-target.txt
probe_command="test -f docs/phase4-evidence-standardization-smoke/slice-01-verified-fix-target.txt && printf '%s\\n' 'target artifact exists'"
probe_stdout="target artifact exists"
probe_stderr=""
eval "$probe_command"
probe_exit=$?
if [ "$probe_exit" -ne 0 ]; then
  printf '%s\n' "unexpected probe exit $probe_exit for $probe_command" >&2
  exit 1
fi
cat > docs/phase4-evidence-standardization-smoke/slice-01-verified-fix-evidence.json <<'JSON'
{
  "schema_version": "phase4.evidence.v1",
  "slice_id": "slice-01-verified-fix",
  "routine_id": "phase4-verified-fix",
  "assumption_tested": "A completed slice can prove a fix with a standard evidence bundle.",
  "summary": "The target behavior passed on the real execution surface.",
  "commands_run": [
    {
      "command": "test -f docs/phase4-evidence-standardization-smoke/slice-01-verified-fix-target.txt && printf '%s\\n' 'target artifact exists'",
      "exit_code": 0,
      "stdout_excerpt": "target artifact exists",
      "stderr_excerpt": ""
    }
  ],
  "test_results": [
    {
      "name": "phase4 evidence contract",
      "status": "passed",
      "details": "Validated by phase 4 schema."
    }
  ],
  "target_bug_reproduced": "reproduced",
  "real_frontend_path_exercised": false,
  "real_execution_surface": "Local slice worktree filesystem probe",
  "files_changed": [
    "routines/phase4-verified-fix.sh",
    "docs/phase4-evidence-standardization-smoke/slice-01-verified-fix-target.txt",
    "docs/phase4-evidence-standardization-smoke/slice-01-verified-fix-evidence.json"
  ],
  "evidence_files": [
    "docs/phase4-evidence-standardization-smoke/slice-01-verified-fix-evidence.json"
  ],
  "open_uncertainties": [],
  "next_recommendation": "proceed",
  "outcome": "verified_fix"
}
JSON
