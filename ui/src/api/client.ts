import type {
  ActivityResponse,
  AgentLogsResponse,
  AgentOption,
  ApproveTaskRequest,
  ChecklistItemSchema,
  ClarificationRequest,
  CreateRunRequest,
  PendingAction,
  PromptResponse,
  RejectTaskRequest,
  RespondToClarificationRequest,
  RoutineDetail,
  RoutineListResponse,
  RunListResponse,
  RunResponse,
  SetGradeRequest,
  TaskDetailResponse,
  TransitionResponse,
  UpdateChecklistRequest,
} from '../types';

const BASE_URL = import.meta.env.VITE_API_URL ?? '';

let authToken: string | null = import.meta.env.VITE_AUTH_TOKEN ?? null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export function getAuthToken(): string | null {
  return authToken;
}

export class ApiError extends Error {
  status: number;
  body: unknown;

  constructor(status: number, body: unknown) {
    super(extractMessage(status, body));
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
  }
}

function extractMessage(status: number, body: unknown): string {
  if (body && typeof body === 'object') {
    const b = body as Record<string, unknown>;
    // Prefer 'detail' field (human-readable), then 'message', then 'reason'
    for (const key of ['detail', 'message', 'reason']) {
      if (typeof b[key] === 'string' && b[key]) return b[key] as string;
    }
    // Build message from 'error' type + contextual fields
    if (typeof b.error === 'string') {
      const label = (b.error as string).replace(/_/g, ' ');
      // Include transition context if present
      if (b.from_status && b.to_status) {
        return `${label}: ${b.from_status} -> ${b.to_status}`;
      }
      return label;
    }
  }
  return `API error ${status}`;
}

async function fetchApi<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string>),
  };

  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  if (init?.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(0, { detail: 'Unable to reach server. Is the backend running?' });
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

export const api = {
  listRuns(params?: { status?: string; project_id?: string }): Promise<RunListResponse> {
    const sp = new URLSearchParams();
    if (params?.status) sp.set('status', params.status);
    if (params?.project_id) sp.set('project_id', params.project_id);
    const qs = sp.toString();
    return fetchApi('/api/runs' + (qs ? '?' + qs : ''));
  },

  getRun(runId: string): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId);
  },

  createRun(req: CreateRunRequest): Promise<RunResponse> {
    return fetchApi('/api/runs', {
      method: 'POST',
      body: JSON.stringify(req),
    });
  },

  startRun(runId: string): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId + '/start', { method: 'POST' });
  },

  pauseRun(runId: string): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId + '/pause', { method: 'POST' });
  },

  resumeRun(runId: string, payload?: { agent_type?: string; agent_config?: Record<string, unknown> }): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId + '/resume', {
      method: 'POST',
      body: payload ? JSON.stringify(payload) : undefined,
    });
  },

  cancelRun(runId: string): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId + '/cancel', { method: 'POST' });
  },

  deleteRun(runId: string): Promise<void> {
    return fetchApi('/api/runs/' + runId, { method: 'DELETE' });
  },

  getTask(runId: string, taskId: string): Promise<TaskDetailResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId);
  },

  startTask(runId: string, taskId: string): Promise<TransitionResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/start', { method: 'POST' });
  },

  submitTask(runId: string, taskId: string): Promise<TransitionResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/submit', { method: 'POST' });
  },

  getTaskPrompt(runId: string, taskId: string): Promise<PromptResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/prompt');
  },

  listRoutines(): Promise<RoutineListResponse> {
    return fetchApi('/api/routines');
  },

  getRoutine(routineId: string): Promise<RoutineDetail> {
    return fetchApi('/api/routines/' + routineId);
  },

  listAgents(): Promise<AgentOption[]> {
    return fetchApi('/api/agents');
  },

  updateChecklist(runId: string, taskId: string, reqId: string, data: UpdateChecklistRequest): Promise<ChecklistItemSchema> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/checklist/' + reqId, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  },

  setGrade(runId: string, taskId: string, reqId: string, data: SetGradeRequest): Promise<ChecklistItemSchema> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/checklist/' + reqId + '/grade', {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  },

  completeVerification(runId: string, taskId: string): Promise<TransitionResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/complete-verification', {
      method: 'POST',
    });
  },

  getActivity(runId: string, params?: { after?: number; limit?: number; event_type?: string }): Promise<ActivityResponse> {
    const sp = new URLSearchParams();
    if (params?.after != null) sp.set('after', String(params.after));
    if (params?.limit != null) sp.set('limit', String(params.limit));
    if (params?.event_type) sp.set('event_type', params.event_type);
    const qs = sp.toString();
    return fetchApi('/api/runs/' + runId + '/activity' + (qs ? '?' + qs : ''));
  },

  getAttemptLogs(runId: string, taskId: string, attemptNum: number): Promise<AgentLogsResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/attempts/' + attemptNum + '/logs');
  },

  getPendingActions(runId: string): Promise<PendingAction[]> {
    return fetchApi('/api/runs/' + runId + '/pending-actions');
  },

  getPendingClarification(runId: string, taskId: string): Promise<ClarificationRequest | null> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/pending-clarification');
  },

  respondToClarification(runId: string, taskId: string, requestId: string, data: RespondToClarificationRequest): Promise<TransitionResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/clarifications/' + requestId + '/respond', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  approveTask(runId: string, taskId: string, data: ApproveTaskRequest): Promise<TransitionResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/approve', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  rejectTask(runId: string, taskId: string, data: RejectTaskRequest): Promise<TransitionResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/reject', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },
};
