import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';
import { useRunWebSocket } from '../../src/hooks/useWebSocket';

vi.mock('../../src/api/client', () => ({ getAuthToken: () => null }));

// Track all WS instances created during a test so we can trigger events on any of them.
class MockWebSocket {
  static instances: MockWebSocket[] = [];

  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
  }

  close() {}
}

beforeEach(() => {
  MockWebSocket.instances = [];
  vi.stubGlobal('WebSocket', MockWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  vi.useRealTimers();
});

function setup(runId = 'r1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const spy = vi.spyOn(qc, 'invalidateQueries');
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  const { result, unmount } = renderHook(() => useRunWebSocket(runId), { wrapper });
  const ws = () => MockWebSocket.instances[MockWebSocket.instances.length - 1];

  function send(data: unknown) {
    act(() => {
      ws().onmessage?.({ data: JSON.stringify(data) } as MessageEvent);
    });
  }

  return { qc, spy, result, unmount, ws, send };
}

// ─── processEvent ─────────────────────────────────────────────────────────────

describe('processEvent — event routing', () => {
  it('approval_requested invalidates pending-actions (regression: bug 1)', () => {
    const { spy, send } = setup();
    send({ event_type: 'approval_requested' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['pending-actions', 'r1'] });
  });

  it('every event always invalidates the activity feed', () => {
    const { spy, send } = setup();
    send({ event_type: 'approval_requested' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['activity', 'r1'] });
  });

  it('run_status_changed invalidates run and runs list', () => {
    const { spy, send } = setup();
    send({ event_type: 'run_status_changed' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['run', 'r1'] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['runs'] });
  });

  it('task_status_changed with task_id invalidates the specific task', () => {
    const { spy, send } = setup();
    send({ event_type: 'task_status_changed', task_id: 't-42' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['task', 'r1', 't-42'] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['run', 'r1'] });
  });

  it('task_status_changed without task_id does not fire the task key', () => {
    const { spy, send } = setup();
    send({ event_type: 'task_status_changed' });
    const taskCalls = spy.mock.calls.filter(([q]) => (q as { queryKey: unknown[] }).queryKey[0] === 'task');
    expect(taskCalls).toHaveLength(0);
  });

  it('clarification_requested invalidates pending-actions', () => {
    const { spy, send } = setup();
    send({ event_type: 'clarification_requested' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['pending-actions', 'r1'] });
  });

  it('clarification_requested with payload.task_id invalidates pending-clarification', () => {
    const { spy, send } = setup();
    send({ event_type: 'clarification_requested', payload: { task_id: 't-7' } });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['pending-clarification', 'r1', 't-7'] });
  });

  it('clarification_responded with payload.task_id invalidates clarification-history', () => {
    const { spy, send } = setup();
    send({ event_type: 'clarification_responded', payload: { task_id: 't-7' } });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['clarification-history', 'r1', 't-7'] });
  });

  it('checklist_gate_evaluated invalidates run cache', () => {
    const { spy, send } = setup();
    send({ event_type: 'checklist_gate_evaluated' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['run', 'r1'] });
  });

  it('checklist_gate_evaluated with task_id invalidates specific task', () => {
    const { spy, send } = setup();
    send({ event_type: 'checklist_gate_evaluated', task_id: 't-5' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['run', 'r1'] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['task', 'r1', 't-5'] });
  });

  it('grades_evaluated invalidates run cache', () => {
    const { spy, send } = setup();
    send({ event_type: 'grades_evaluated' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['run', 'r1'] });
  });

  it('grades_evaluated with task_id invalidates specific task', () => {
    const { spy, send } = setup();
    send({ event_type: 'grades_evaluated', task_id: 't-9' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['task', 'r1', 't-9'] });
  });

  it('unknown event type falls back to invalidating the run', () => {
    const { spy, send } = setup();
    send({ event_type: 'some_future_event_type' });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['run', 'r1'] });
  });

  it('batch message processes each contained event', () => {
    const { spy, send } = setup();
    send({
      type: 'batch',
      events: [
        { event_type: 'approval_requested' },
        { event_type: 'run_status_changed' },
      ],
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['pending-actions', 'r1'] });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['runs'] });
  });

  it('malformed JSON is swallowed without throwing', () => {
    const { ws } = setup();
    expect(() => {
      act(() => {
        ws().onmessage?.({ data: 'not-json{{{{' } as MessageEvent);
      });
    }).not.toThrow();
  });
});

// ─── No extra invalidations (performance regression guard) ────────────────────

describe('processEvent — no extra invalidations', () => {
  it('approval_requested fires exactly 2 invalidations (activity + pending-actions)', () => {
    const { spy, send } = setup();
    send({ event_type: 'approval_requested' });
    expect(spy).toHaveBeenCalledTimes(2);
    const keys = spy.mock.calls.map(([q]) => (q as { queryKey: unknown[] }).queryKey[0]);
    expect(keys).toContain('activity');
    expect(keys).toContain('pending-actions');
  });

  it('run_status_changed fires exactly 3 invalidations (activity + run + runs)', () => {
    const { spy, send } = setup();
    send({ event_type: 'run_status_changed' });
    expect(spy).toHaveBeenCalledTimes(3);
    const keys = spy.mock.calls.map(([q]) => (q as { queryKey: unknown[] }).queryKey[0]);
    expect(keys).toContain('activity');
    expect(keys).toContain('run');
    expect(keys).toContain('runs');
  });

  it('task_status_changed without task_id fires exactly 2 invalidations (activity + run)', () => {
    const { spy, send } = setup();
    send({ event_type: 'task_status_changed' });
    expect(spy).toHaveBeenCalledTimes(2);
    const keys = spy.mock.calls.map(([q]) => (q as { queryKey: unknown[] }).queryKey[0]);
    expect(keys).toContain('activity');
    expect(keys).toContain('run');
  });

  it('task_status_changed with task_id fires exactly 3 invalidations (activity + run + task)', () => {
    const { spy, send } = setup();
    send({ event_type: 'task_status_changed', task_id: 't-1' });
    expect(spy).toHaveBeenCalledTimes(3);
    const keys = spy.mock.calls.map(([q]) => (q as { queryKey: unknown[] }).queryKey[0]);
    expect(keys).toContain('activity');
    expect(keys).toContain('run');
    expect(keys).toContain('task');
  });

  it('clarification_responded without task_id fires exactly 1 invalidation (activity only)', () => {
    const { spy, send } = setup();
    send({ event_type: 'clarification_responded' });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith({ queryKey: ['activity', 'r1'] });
  });
});

// ─── Reconnect backoff ─────────────────────────────────────────────────────────

describe('reconnection', () => {
  it('reconnects after close with initial 1s delay', () => {
    vi.useFakeTimers();
    setup();

    act(() => { MockWebSocket.instances[0].onclose?.({} as CloseEvent); });
    expect(MockWebSocket.instances).toHaveLength(1);

    act(() => { vi.advanceTimersByTime(1000); });
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('doubles delay on each subsequent close', () => {
    vi.useFakeTimers();
    setup();

    // Close 1 → 1s delay
    act(() => { MockWebSocket.instances[0].onclose?.({} as CloseEvent); });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(MockWebSocket.instances).toHaveLength(2);

    // Close 2 → 2s delay; 1s is not enough
    act(() => { MockWebSocket.instances[1].onclose?.({} as CloseEvent); });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(MockWebSocket.instances).toHaveLength(2);

    act(() => { vi.advanceTimersByTime(1000); });
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it('does not reconnect after unmount', () => {
    vi.useFakeTimers();
    const { unmount } = setup();

    act(() => { MockWebSocket.instances[0].onclose?.({} as CloseEvent); });
    unmount();

    act(() => { vi.advanceTimersByTime(2000); });
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it('resets attempt counter on successful connect', () => {
    vi.useFakeTimers();
    setup();

    // Two closes to advance attempt counter to 2
    act(() => { MockWebSocket.instances[0].onclose?.({} as CloseEvent); });
    act(() => { vi.advanceTimersByTime(1000); });
    act(() => { MockWebSocket.instances[1].onclose?.({} as CloseEvent); });
    act(() => { vi.advanceTimersByTime(2000); });
    expect(MockWebSocket.instances).toHaveLength(3);

    // Successful open resets counter
    act(() => { MockWebSocket.instances[2].onopen?.({} as Event); });

    // Next close should use 1s delay again (attempt reset to 0)
    act(() => { MockWebSocket.instances[2].onclose?.({} as CloseEvent); });
    act(() => { vi.advanceTimersByTime(1000); });
    expect(MockWebSocket.instances).toHaveLength(4);
  });
});
