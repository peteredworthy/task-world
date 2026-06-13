import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { SchedulerView } from '../SchedulerView';
import type { SchedulerViewResponse } from '../../types';

afterEach(cleanup);

describe('SchedulerView', () => {
  it('renders scheduler buckets and active/suspended leases from fixture data', () => {
    const view: SchedulerViewResponse = {
      run_id: 'run-1',
      event_count: 7,
      scheduler: {
        ready: ['worker-ready'],
        blocked: [{ node_id: 'verifier-blocked', reason: 'missing_required_input:candidate' }],
        waiting_resources: [{ node_id: 'worker-resource', reason: 'resource_conflict:write:write' }],
        waiting_gates: [{ node_id: 'gate-wait', reason: 'gate_not_approved:gate-1' }],
      },
      leases: {
        active: [
          {
            lease_id: 'lease-active',
            node_id: 'worker-ready',
            generation: 1,
            state: 'active',
            execution_id: 'exec-active',
            expires_at: '2026-06-13T12:05:00Z',
          },
        ],
        suspended: [
          {
            lease_id: 'lease-suspended',
            node_id: 'worker-paused',
            generation: 2,
            state: 'suspended',
            execution_id: 'exec-suspended',
            expires_at: '2026-06-13T12:10:00Z',
          },
        ],
      },
    };

    render(<SchedulerView view={view} />);

    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText('Blocked')).toBeTruthy();
    expect(screen.getByText('Waiting resources')).toBeTruthy();
    expect(screen.getByText('Waiting gates')).toBeTruthy();
    expect(screen.getAllByText('worker-ready')).toHaveLength(2);
    expect(screen.getByText('verifier-blocked')).toBeTruthy();
    expect(screen.getByText('missing_required_input:candidate')).toBeTruthy();
    expect(screen.getByText('worker-resource')).toBeTruthy();
    expect(screen.getByText('resource_conflict:write:write')).toBeTruthy();
    expect(screen.getByText('gate-wait')).toBeTruthy();
    expect(screen.getByText('gate_not_approved:gate-1')).toBeTruthy();
    expect(screen.getByText('lease-active')).toBeTruthy();
    expect(screen.getByText('lease-suspended')).toBeTruthy();
    expect(screen.getByText('suspended')).toBeTruthy();
  });
});
