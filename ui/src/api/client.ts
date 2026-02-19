import type {
  ActivityResponse,
  AgentLogsResponse,
  AgentOption,
  ApproveTaskRequest,
  BranchStatusResponse,
  BranchCountResponse,
  BranchesListResponse,
  ChecklistItemSchema,
  ClarificationRequest,
  CreateRunRequest,
  EnvDefaultTarget,
  EnvFile,
  EnvSnapshot,
  GlobalConfig,
  GuidanceResponse,
  PendingAction,
  ProjectRoutineResponse,
  ProjectRoutinesListResponse,
  RecoverRequest,
  RecoverResponse,
  PromptResponse,
  RejectTaskRequest,
  RepoResponse,
  ReposListResponse,
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
import { joinBaseUrl, normalizeBaseUrl } from '../lib/url';

const BASE_URL = normalizeBaseUrl(import.meta.env.VITE_API_URL);

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

export class RecoverTaskNotFoundError extends ApiError {
  constructor(body: unknown) {
    super(404, body);
    this.name = 'RecoverTaskNotFoundError';
  }
}

export class RecoverInvalidStateError extends ApiError {
  constructor(body: unknown) {
    super(409, body);
    this.name = 'RecoverInvalidStateError';
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
    res = await fetch(joinBaseUrl(BASE_URL, path), { ...init, headers });
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

function normalizeEnvFile(value: unknown): EnvFile | null {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const file = value as Record<string, unknown>;
  const path =
    typeof file.path === 'string'
      ? file.path
      : typeof file.file_path === 'string'
        ? file.file_path
        : '';
  const key = typeof file.key === 'string' ? file.key : '';
  const maskedValue =
    typeof file.masked_value === 'string'
      ? file.masked_value
      : typeof file.value_masked === 'string'
        ? file.value_masked
        : '';

  if (!path && !key) {
    return null;
  }

  return {
    path,
    key,
    masked_value: maskedValue,
  };
}

function normalizeEnvFiles(value: unknown): EnvFile[] {
  if (Array.isArray(value)) {
    return value.map(normalizeEnvFile).filter((v): v is EnvFile => v !== null);
  }

  if (!value || typeof value !== 'object') {
    return [];
  }

  const obj = value as Record<string, unknown>;
  const candidates = [obj.files, obj.env_files, obj.managed_files];
  const list = candidates.find(Array.isArray);
  if (!Array.isArray(list)) {
    return [];
  }

  return list.map(normalizeEnvFile).filter((v): v is EnvFile => v !== null);
}

function normalizeEnvSnapshot(value: unknown): EnvSnapshot | null {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const snapshot = value as Record<string, unknown>;
  const id =
    typeof snapshot.id === 'string'
      ? snapshot.id
      : typeof snapshot.snapshot_id === 'string'
        ? snapshot.snapshot_id
        : '';
  if (!id) {
    return null;
  }

  const timestamp = typeof snapshot.timestamp === 'string' ? snapshot.timestamp : '';
  const agent =
    typeof snapshot.agent === 'string'
      ? snapshot.agent
      : typeof snapshot.type === 'string'
        ? snapshot.type
        : '';

  let files: EnvFile[] = [];
  if (Array.isArray(snapshot.files)) {
    files = snapshot.files
      .map((file): EnvFile | null => {
        if (typeof file === 'string') {
          return { path: file, key: '', masked_value: '' };
        }
        return normalizeEnvFile(file);
      })
      .filter((file): file is EnvFile => file !== null);
  }

  return {
    id,
    timestamp,
    agent,
    files,
  };
}

function normalizeEnvSnapshots(value: unknown): EnvSnapshot[] {
  if (Array.isArray(value)) {
    return value.map(normalizeEnvSnapshot).filter((v): v is EnvSnapshot => v !== null);
  }

  if (!value || typeof value !== 'object') {
    return [];
  }

  const obj = value as Record<string, unknown>;
  const snapshots = Array.isArray(obj.snapshots) ? obj.snapshots : [];
  return snapshots.map(normalizeEnvSnapshot).filter((v): v is EnvSnapshot => v !== null);
}

function normalizeEnvDefaultTarget(value: unknown): EnvDefaultTarget {
  if (!value || typeof value !== 'object') {
    return { target_path: '' };
  }

  const obj = value as Record<string, unknown>;
  if (typeof obj.target_path === 'string') {
    return { target_path: obj.target_path };
  }
  if (typeof obj.default_target === 'string') {
    return { target_path: obj.default_target };
  }

  return { target_path: '' };
}

export const api = {
  getConfig(): Promise<GlobalConfig> {
    return fetchApi('/api/config');
  },

  listRuns(params?: { status?: string; repo_name?: string; limit?: number }): Promise<RunListResponse> {
    const sp = new URLSearchParams();
    if (params?.status) sp.set('status', params.status);
    if (params?.repo_name) sp.set('repo_name', params.repo_name);
    if (params?.limit !== undefined) sp.set('limit', String(params.limit));
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

  agentStarted(runId: string): Promise<void> {
    return fetchApi('/api/runs/' + runId + '/agent-started', { method: 'POST' });
  },

  agentCancelled(runId: string): Promise<void> {
    return fetchApi('/api/runs/' + runId + '/agent-cancelled', { method: 'POST' });
  },

  transitionBack(runId: string, data: { target_step_index: number; reason?: string }): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId + '/transition-back', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  getGuidance(runId: string): Promise<GuidanceResponse> {
    return fetchApi('/api/runs/' + runId + '/guidance');
  },

  getBranchStatus(runId: string): Promise<BranchStatusResponse> {
    return fetchApi('/api/runs/' + runId + '/branch-status');
  },

  backMerge(runId: string): Promise<void> {
    return fetchApi('/api/runs/' + runId + '/back-merge', { method: 'POST' });
  },

  async recoverRun(runId: string, data: RecoverRequest): Promise<RecoverResponse> {
    try {
      return await fetchApi('/api/runs/' + runId + '/recover', {
        method: 'POST',
        body: JSON.stringify(data),
      });
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 404) {
          throw new RecoverTaskNotFoundError(error.body);
        }
        if (error.status === 409) {
          throw new RecoverInvalidStateError(error.body);
        }
      }
      throw error;
    }
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

  async getEnvFiles(runId: string): Promise<EnvFile[]> {
    const response = await fetchApi<unknown>('/api/runs/' + runId + '/env-files');
    return normalizeEnvFiles(response);
  },

  async getEnvSnapshots(runId: string): Promise<EnvSnapshot[]> {
    const response = await fetchApi<unknown>('/api/runs/' + runId + '/env-files/snapshots');
    return normalizeEnvSnapshots(response);
  },

  async getEnvDefaultTarget(runId: string): Promise<EnvDefaultTarget> {
    const response = await fetchApi<unknown>('/api/runs/' + runId + '/env-files/default-target');
    return normalizeEnvDefaultTarget(response);
  },

  async revertEnvSnapshot(runId: string, snapshotId: string): Promise<EnvSnapshot> {
    const response = await fetchApi<unknown>('/api/runs/' + runId + '/env-files/revert', {
      method: 'POST',
      body: JSON.stringify({
        snapshot_id: snapshotId,
        revert_to: snapshotId,
      }),
    });

    const normalized = normalizeEnvSnapshot(response);
    return normalized ?? { id: snapshotId, timestamp: '', agent: '', files: [] };
  },

  copyBackEnvFiles(runId: string, targetPath: string): Promise<void> {
    return fetchApi('/api/runs/' + runId + '/env-files/copy-back', {
      method: 'POST',
      body: JSON.stringify({
        target_path: targetPath,
        target_dir: targetPath,
      }),
    });
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

  approveStep(runId: string, stepId: string, data: { approved_by: string; comment?: string }): Promise<unknown> {
    return fetchApi('/api/runs/' + runId + '/steps/' + stepId + '/approve', {
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

  mergeBack(runId: string, options?: { strategy?: string; dirty_action?: 'stash' | 'commit' }): Promise<{ merge_commit: string; strategy: string; message: string }> {
    const body: Record<string, string> = {};
    if (options?.strategy) body.strategy = options.strategy;
    if (options?.dirty_action) body.dirty_action = options.dirty_action;
    return fetchApi('/api/runs/' + runId + '/merge-back', {
      method: 'POST',
      body: Object.keys(body).length > 0 ? JSON.stringify(body) : undefined,
    });
  },

  // Repos API
  listRepos(): Promise<ReposListResponse> {
    return fetchApi('/api/repos');
  },

  getRepo(name: string): Promise<RepoResponse> {
    return fetchApi('/api/repos/' + name);
  },

  listBranches(repoName: string, params?: { pattern?: string; include_remote?: boolean }): Promise<BranchesListResponse> {
    const sp = new URLSearchParams();
    if (params?.pattern) sp.set('pattern', params.pattern);
    if (params?.include_remote !== undefined) sp.set('include_remote', String(params.include_remote));
    const qs = sp.toString();
    return fetchApi('/api/repos/' + repoName + '/branches' + (qs ? '?' + qs : ''));
  },

  countBranches(repoName: string, params?: { pattern?: string; include_remote?: boolean }): Promise<BranchCountResponse> {
    const sp = new URLSearchParams();
    if (params?.pattern) sp.set('pattern', params.pattern);
    if (params?.include_remote !== undefined) sp.set('include_remote', String(params.include_remote));
    const qs = sp.toString();
    return fetchApi('/api/repos/' + repoName + '/branches/count' + (qs ? '?' + qs : ''));
  },

  listRepoRoutines(repoName: string, branch: string): Promise<ProjectRoutinesListResponse> {
    return fetchApi('/api/repos/' + repoName + '/routines?branch=' + encodeURIComponent(branch));
  },

  getRepoRoutine(repoName: string, routineId: string, branch: string): Promise<ProjectRoutineResponse> {
    return fetchApi('/api/repos/' + repoName + '/routines/' + routineId + '?branch=' + encodeURIComponent(branch));
  },
};

export function recoverRun(runId: string, data: RecoverRequest): Promise<RecoverResponse> {
  return api.recoverRun(runId, data);
}

export function approveStep(runId: string, stepId: string, data: { approved_by: string; comment?: string }): Promise<unknown> {
  return api.approveStep(runId, stepId, data);
}

export function agentStarted(runId: string): Promise<void> {
  return api.agentStarted(runId);
}

export function agentCancelled(runId: string): Promise<void> {
  return api.agentCancelled(runId);
}

export function transitionBack(runId: string, data: { target_step_index: number; reason?: string }): Promise<RunResponse> {
  return api.transitionBack(runId, data);
}

export function getGuidance(runId: string): Promise<GuidanceResponse> {
  return api.getGuidance(runId);
}

export function getBranchStatus(runId: string): Promise<BranchStatusResponse> {
  return api.getBranchStatus(runId);
}

export function backMerge(runId: string): Promise<void> {
  return api.backMerge(runId);
}

export function getEnvFiles(runId: string): Promise<EnvFile[]> {
  return api.getEnvFiles(runId);
}

export function getEnvSnapshots(runId: string): Promise<EnvSnapshot[]> {
  return api.getEnvSnapshots(runId);
}

export function getEnvDefaultTarget(runId: string): Promise<EnvDefaultTarget> {
  return api.getEnvDefaultTarget(runId);
}

export function revertEnvSnapshot(runId: string, snapshotId: string): Promise<EnvSnapshot> {
  return api.revertEnvSnapshot(runId, snapshotId);
}

export function copyBackEnvFiles(runId: string, targetPath: string): Promise<void> {
  return api.copyBackEnvFiles(runId, targetPath);
}

export function getConfig(): Promise<GlobalConfig> {
  return api.getConfig();
}
