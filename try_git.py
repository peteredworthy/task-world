#!/usr/bin/env python3
import subprocess
import sys

result = subprocess.run(['/usr/bin/git', 'add', 'docs/per-model-yaml/ctx/step-*-plan-plan-context.md'],
                       capture_output=True, text=True)
print("Return code:", result.returncode)
print("STDERR:", result.stderr)
if result.returncode == 0:
    result2 = subprocess.run(['/usr/bin/git', 'commit', '-m', 'Add plan context files for per-model token accounting steps'],
                            capture_output=True, text=True)
    print("Commit return code:", result2.returncode)
    print("Commit output:", result2.stdout)
    print("Commit stderr:", result2.stderr)
