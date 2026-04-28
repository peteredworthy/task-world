#!/bin/sh
set -u
mkdir -p docs/phase4-evidence-standardization-smoke
probe_command="test -x .phase4/browser-runtime || { printf '%s\\n' 'browser runtime marker missing' >&2; false; }"
probe_stdout=""
probe_stderr="browser runtime marker missing"
eval "$probe_command"
probe_exit=$?
if [ "$probe_exit" -ne 1 ]; then
  printf '%s\n' "unexpected probe exit $probe_exit for $probe_command" >&2
  exit 1
fi
cat > docs/phase4-evidence-standardization-smoke/slice-03-environment-blocked-evidence.json <<'JSON'
{
  "schema_version": "phase4.evidence.v1",
  "slice_id": "slice-03-environment-blocked",
  "routine_id": "phase4-environment-blocked",
  "assumption_tested": "A slice can preserve environment failures without mislabeling them as fixes.",
  "summary": "The browser surface could not run, so the result is blocked.",
  "commands_run": [
    {
      "command": "test -x .phase4/browser-runtime || { printf '%s\\n' 'browser runtime marker missing' >&2; false; }",
      "exit_code": 1,
      "stdout_excerpt": "",
      "stderr_excerpt": "browser runtime marker missing"
    }
  ],
  "test_results": [
    {
      "name": "phase4 evidence contract",
      "status": "skipped",
      "details": "Validated by phase 4 schema."
    }
  ],
  "target_bug_reproduced": "unknown",
  "real_frontend_path_exercised": false,
  "real_execution_surface": "Local browser-runtime availability probe",
  "files_changed": [
    "routines/phase4-environment-blocked.sh",
    "docs/phase4-evidence-standardization-smoke/slice-03-environment-blocked-evidence.json"
  ],
  "evidence_files": [
    "docs/phase4-evidence-standardization-smoke/slice-03-environment-blocked-evidence.json"
  ],
  "open_uncertainties": [
    "Install or expose the browser runtime before replanning."
  ],
  "next_recommendation": "environment_blocked",
  "outcome": "environment_blocked"
}
JSON
