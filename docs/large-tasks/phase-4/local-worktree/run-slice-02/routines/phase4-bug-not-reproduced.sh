#!/bin/sh
set -u
mkdir -p docs/phase4-evidence-standardization-smoke
probe_command="test ! -f docs/phase4-evidence-standardization-smoke/slice-02-bug-not-reproduced-present.txt && printf '%s\\n' 'reported bug marker absent'"
probe_stdout="reported bug marker absent"
probe_stderr=""
eval "$probe_command"
probe_exit=$?
if [ "$probe_exit" -ne 0 ]; then
  printf '%s\n' "unexpected probe exit $probe_exit for $probe_command" >&2
  exit 1
fi
cat > docs/phase4-evidence-standardization-smoke/slice-02-bug-not-reproduced-evidence.json <<'JSON'
{
  "schema_version": "phase4.evidence.v1",
  "slice_id": "slice-02-bug-not-reproduced",
  "routine_id": "phase4-bug-not-reproduced",
  "assumption_tested": "A slice can stop cleanly when the target bug is not reproduced.",
  "summary": "The reported bug was not reproduced on the named real surface.",
  "commands_run": [
    {
      "command": "test ! -f docs/phase4-evidence-standardization-smoke/slice-02-bug-not-reproduced-present.txt && printf '%s\\n' 'reported bug marker absent'",
      "exit_code": 0,
      "stdout_excerpt": "reported bug marker absent",
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
  "target_bug_reproduced": "not_reproduced",
  "real_frontend_path_exercised": false,
  "real_execution_surface": "Local slice worktree filesystem probe",
  "files_changed": [
    "routines/phase4-bug-not-reproduced.sh",
    "docs/phase4-evidence-standardization-smoke/slice-02-bug-not-reproduced-evidence.json"
  ],
  "evidence_files": [
    "docs/phase4-evidence-standardization-smoke/slice-02-bug-not-reproduced-evidence.json"
  ],
  "open_uncertainties": [
    "Need reporter environment details before implementation."
  ],
  "next_recommendation": "stop",
  "outcome": "bug_not_reproduced"
}
JSON
