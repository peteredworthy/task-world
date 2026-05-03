// AUTO-GENERATED — do not edit by hand.
// Source: src/orchestrator/config/enums.py
// Run `uv run python scripts/export_enums.py` to regenerate.

export type RunStatus = 'draft' | 'active' | 'paused' | 'stopping' | 'completed' | 'failed';

export type TaskStatus = 'pending' | 'building' | 'pending_user_action' | 'verifying' | 'recovering' | 'fan_out_running' | 'completed' | 'failed';

export type ChecklistStatus = 'open' | 'done' | 'not_applicable' | 'blocked' | 'escalated';

export type Priority = 'critical' | 'expected' | 'nice';

export type AgentRunnerType = 'openhands_local' | 'openhands_docker' | 'cli_subprocess' | 'user_managed' | 'codex_server' | 'claude_sdk';

export type RoutineSource = 'local' | 'embedded' | 'project';

export type GateType = 'checklist' | 'grade_threshold' | 'human_approval' | 'auto_verify';

export type MergeStrategy = 'squash' | 'merge';

export type StepType = 'standard' | 'dry_run';

export type Complexity = 'simple' | 'standard';

export type ModelProfile = 'architect' | 'designer' | 'coder' | 'summarizer';
