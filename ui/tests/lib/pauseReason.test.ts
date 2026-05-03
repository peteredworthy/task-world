import { describe, it, expect } from 'vitest';
import { getPauseReasonMessage } from '../../src/lib/pauseReason';

function run(pause_reason: string, agent_runner_type = 'claude') {
  return { pause_reason, agent_runner_type };
}

describe('getPauseReasonMessage', () => {
  it('returns empty string when pause_reason is null', () => {
    expect(getPauseReasonMessage({ pause_reason: null, agent_runner_type: 'claude' })).toBe('');
  });

  const CASES: Array<[string, string, string?]> = [
    ['server_shutdown', 'Paused — server restarted; resume will continue from the current task'],
    ['executor_not_started', 'Paused — executor startup safety marker; this should clear automatically within a few seconds'],
    ['agent_not_available', 'Paused — selected agent runner is not available'],
    ['agent_execution_error', 'Paused — agent execution error'],
    ['agent_exit_failure', 'Paused — agent exited with error'],
    ['gate_blocked', 'Paused — checklist gate not satisfied'],
    ['manual_gate', 'Paused — waiting at manual gate'],
    ['recovery_loop', 'Paused — recovery loop detected'],
    ['unexpected_error', 'Paused — unexpected error'],
    ['agent_health_check_failed', 'Paused — agent health check failed'],
    ['agent_not_running_on_startup', 'Paused — agent was not running when the server started'],
    ['recovered', 'Paused — recovered from failure'],
    ['recovery_triggered', 'Paused — recovery triggered'],
    ['requirement_escalated', 'Paused — agent flagged an unfulfillable requirement'],
    ['waiting_for_approval', 'Paused — waiting for step approval'],
    ['awaiting_approval', 'Paused — waiting for step approval'],
    ['awaiting_user_input', 'Paused — waiting for user input'],
    ['fan_out_child_failed', 'Paused — one or more fan-out children failed'],
    ['fan_out_orphaned', 'Paused — fan-out task needs recovery'],
    ['rate_limit', 'Paused — API rate or credit limit hit'],
    ['all_steps_complete_but_active', 'Paused — all steps complete but run stayed active'],
    ['no_actionable_tasks', 'Paused — no actionable tasks in current step'],
    ['no_executor_running', 'Paused — no executor is running. Resume the run to start a managed runner.', 'claude'],
    ['no_executor_running', 'Paused — no managed executor is attached. Connect an external agent or resume with a managed runner.', 'user_managed'],
  ];

  for (const [reason, expected, agentType] of CASES) {
    it(`${reason}${agentType ? ` (${agentType})` : ''}`, () => {
      expect(getPauseReasonMessage(run(reason, agentType ?? 'claude'))).toBe(expected);
    });
  }

  it('falls back to Paused (reason) for unknown reasons', () => {
    expect(getPauseReasonMessage(run('some_future_reason'))).toBe('Paused (some_future_reason)');
  });
});
