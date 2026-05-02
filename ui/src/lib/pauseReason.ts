import type { RunResponse } from '../types/runs';

export function getPauseReasonMessage(run: Pick<RunResponse, 'pause_reason' | 'agent_type'>): string {
  if (!run.pause_reason) return '';

  if (run.pause_reason === 'no_executor_running') {
    if (run.agent_type === 'user_managed') {
      return 'Paused — no managed executor is attached. Connect an external agent or resume with a managed runner.';
    }
    return 'Paused — no executor is running. Resume the run to start a managed runner.';
  }

  const messages: Record<string, string> = {
    server_shutdown: 'Paused — server restarted; resume will continue from the current task',
    executor_not_started: 'Paused — executor startup safety marker; this should clear automatically within a few seconds',
    agent_not_available: 'Paused — selected agent runner is not available',
    agent_execution_error: 'Paused — agent execution error',
    agent_exit_failure: 'Paused — agent exited with error',
    gate_blocked: 'Paused — checklist gate not satisfied',
    manual_gate: 'Paused — waiting at manual gate',
    recovery_loop: 'Paused — recovery loop detected',
    unexpected_error: 'Paused — unexpected error',
    agent_health_check_failed: 'Paused — agent health check failed',
    agent_not_running_on_startup: 'Paused — agent was not running when the server started',
    recovered: 'Paused — recovered from failure',
    recovery_triggered: 'Paused — recovery triggered',
    requirement_escalated: 'Paused — agent flagged an unfulfillable requirement',
    waiting_for_approval: 'Paused — waiting for step approval',
    awaiting_approval: 'Paused — waiting for step approval',
    awaiting_user_input: 'Paused — waiting for user input',
    fan_out_child_failed: 'Paused — one or more fan-out children failed',
    fan_out_orphaned: 'Paused — fan-out task needs recovery',
    rate_limit: 'Paused — API rate or credit limit hit',
    all_steps_complete_but_active: 'Paused — all steps complete but run stayed active',
    no_actionable_tasks: 'Paused — no actionable tasks in current step',
  };

  return messages[run.pause_reason] ?? `Paused (${run.pause_reason})`;
}
