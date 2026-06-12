import type {
  ActivityResponse,
  AgentLogsResponse,
  AgentRunnerOption,
  AttemptSchema,
  ApproveTaskRequest,
  ForceAcceptTaskRequest,
  ArchiveRoutineResponse,
  BranchStatusResponse,
  BranchCountResponse,
  BranchesListResponse,
  ChecklistItemSchema,
  ClarificationRequest,
  CreateRunRequest,
  EnvDefaultTarget,
  EnvFile,
  EnvSnapshot,
  GraphEventResponse,
  GraphProjectionResponse,
  NodeDetailResponse,
  GlobalConfig,
  ModelProfileInfo,
  PendingAction,
  AcceptChildRunResponse,
  ParentOversightResponse,
  ProjectRoutineResponse,
  ProjectRoutinesListResponse,
  RecoverRequest,
  RecoverResponse,
  PromptResponse,
  RejectTaskRequest,
  RepoResponse,
  ReposListResponse,
  RepoStatsResponse,
  RespondToClarificationRequest,
  RoutineDetail,
  RoutineListResponse,
  RunListResponse,
  RunResponse,
  RunTraceResponse,
  AgentRunnerModelDefaults,
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

export interface ValidationError {
  line: number;
  message: string;
}

export interface ValidationResult {
  valid: boolean;
  errors: ValidationError[];
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

function parseValidationLine(rawError: string): number {
  const lineMatch = rawError.match(/\bline\s+(\d+)\b/i);
  if (lineMatch) {
    return Number(lineMatch[1]);
  }
  return 0;
}

function normalizeValidationErrors(rawErrors: unknown): ValidationError[] {
  if (!Array.isArray(rawErrors)) {
    return [];
  }

  return rawErrors.map((entry) => {
    const rawMessage = typeof entry === 'string' ? entry : String(entry);
    return {
      line: parseValidationLine(rawMessage),
      message: rawMessage,
    };
  });
}

export async function fetchApi<T>(path: string, init?: RequestInit): Promise<T> {
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

interface RawRunTraceAttempt {
  step_id: string;
  step_config_id: string;
  step_title?: string;
  step_index: number;
  task_id: string;
  task_config_id: string;
  task_title?: string;
  task_status: RunTraceResponse['attempts'][number]['task_status'];
  task_index?: number;
  attempt: AttemptSchema;
  phases?: RunTraceResponse['attempts'][number]['phases'];
  action_log: RunTraceResponse['attempts'][number]['action_log'];
}

interface RawRunTraceResponse {
  run_id: string;
  attempts: RawRunTraceAttempt[];
}

function normalizeRunTrace(response: RawRunTraceResponse): RunTraceResponse {
  return {
    run_id: response.run_id,
    attempts: response.attempts.map((row) => ({
      step_id: row.step_id,
      step_config_id: row.step_config_id,
      step_title: row.step_title ?? '',
      step_index: row.step_index,
      task_id: row.task_id,
      task_config_id: row.task_config_id,
      task_title: row.task_title ?? '',
      task_status: row.task_status,
      task_index: row.task_index ?? 0,
      attempt_id: row.attempt.id,
      attempt_num: row.attempt.attempt_num,
      started_at: row.attempt.started_at,
      completed_at: row.attempt.completed_at,
      outcome: row.attempt.outcome,
      metrics: row.attempt.metrics,
      token_usage_by_model: row.attempt.token_usage_by_model,
      agent_runner_type: row.attempt.agent_runner_type,
      agent_model: row.attempt.agent_model,
      agent_settings: row.attempt.agent_settings,
      builder_prompt: row.attempt.builder_prompt,
      verifier_prompt: row.attempt.verifier_prompt,
      verifier_comment: row.attempt.verifier_comment,
      error: row.attempt.error,
      phases: row.phases ?? [],
      action_log: row.action_log,
    })),
  };
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

  resumeRun(runId: string, payload?: { agent_runner_type?: string; agent_runner_config?: Record<string, unknown>; resume_strategy?: string }): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId + '/resume', {
      method: 'POST',
      body: payload ? JSON.stringify(payload) : undefined,
    });
  },

  cancelRun(runId: string): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId + '/cancel', { method: 'POST' });
  },

  transitionBack(runId: string, data: { target_step_index: number; reason?: string }): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId + '/transition-back', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  skipStep(runId: string, stepId: string): Promise<RunResponse> {
    return fetchApi('/api/runs/' + runId + '/steps/' + stepId + '/skip', {
      method: 'POST',
    });
  },

  getBranchStatus(runId: string): Promise<BranchStatusResponse> {
    return fetchApi('/api/runs/' + runId + '/branch-status');
  },

  getParentOversight(runId: string): Promise<ParentOversightResponse> {
    return fetchApi('/api/runs/' + runId + '/oversight');
  },

  refreshParentOversight(runId: string): Promise<ParentOversightResponse> {
    return fetchApi('/api/runs/' + runId + '/oversight/refresh', { method: 'POST' });
  },

  acceptChildRun(parentRunId: string, childRunId: string): Promise<AcceptChildRunResponse> {
    return fetchApi('/api/runs/' + parentRunId + '/children/' + childRunId + '/accept', {
      method: 'POST',
    });
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

  listRoutines(params?: { includeArchived?: boolean }): Promise<RoutineListResponse> {
    const sp = new URLSearchParams();
    if (params?.includeArchived) sp.set('include_archived', 'true');
    const qs = sp.toString();
    return fetchApi('/api/routines' + (qs ? '?' + qs : ''));
  },

  getRoutine(routineId: string): Promise<RoutineDetail> {
    return fetchApi('/api/routines/' + routineId);
  },

  archiveRoutine(routineId: string): Promise<ArchiveRoutineResponse> {
    return fetchApi('/api/routines/' + routineId + '/archive', { method: 'POST' });
  },

  unarchiveRoutine(routineId: string): Promise<ArchiveRoutineResponse> {
    return fetchApi('/api/routines/' + routineId + '/unarchive', { method: 'POST' });
  },

  async validateRoutine(yamlContent: string): Promise<ValidationResult> {
    const response = await fetchApi<{ valid: boolean; errors?: unknown }>('/api/routines/validate', {
      method: 'POST',
      body: JSON.stringify({ yaml_content: yamlContent }),
    });

    return {
      valid: response.valid,
      errors: normalizeValidationErrors(response.errors),
    };
  },

  listAgentRunners(): Promise<AgentRunnerOption[]> {
    return fetchApi('/api/agent-runners');
  },

  discoverLocalModels(baseUrl: string): Promise<{ models: string[]; error?: string }> {
    return fetchApi('/api/agent-runners/local-models?base_url=' + encodeURIComponent(baseUrl));
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

  getRunGraphProjection(runId: string): Promise<GraphProjectionResponse> {
    return fetchApi('/api/runs/' + runId + '/graph');
  },

  getRunGraphEvents(runId: string, fromPosition?: number): Promise<GraphEventResponse[]> {
    const sp = new URLSearchParams();
    if (fromPosition !== undefined) {
      sp.set('from_position', String(fromPosition));
    }
    const qs = sp.toString();
    return fetchApi('/api/runs/' + runId + '/graph/events' + (qs ? '?' + qs : ''));
  },

  getRunGraphNodeDetail(runId: string, nodeId: string): Promise<NodeDetailResponse> {
    return fetchApi('/api/runs/' + runId + '/graph/nodes/' + nodeId);
  },

  getActivity(runId: string, params?: { after?: number; limit?: number; event_type?: string }): Promise<ActivityResponse> {
    const sp = new URLSearchParams();
    if (params?.after != null) sp.set('after', String(params.after));
    if (params?.limit != null) sp.set('limit', String(params.limit));
    if (params?.event_type) sp.set('event_type', params.event_type);
    const qs = sp.toString();
    return fetchApi('/api/runs/' + runId + '/activity' + (qs ? '?' + qs : ''));
  },

  async getRunTrace(runId: string): Promise<RunTraceResponse> {
    const response = await fetchApi<RawRunTraceResponse>('/api/runs/' + runId + '/trace');
    return normalizeRunTrace(response);
  },

  getAttemptLogs(runId: string, taskId: string, attemptNum: number): Promise<AgentLogsResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/attempts/' + attemptNum + '/logs');
  },

  getPendingActions(runId: string): Promise<PendingAction[]> {
    return fetchApi('/api/runs/' + runId + '/pending-actions');
  },

  getPendingClarification(runId: string, taskId: string): Promise<ClarificationRequest | null> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/clarifications/pending');
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

  forceAcceptTask(runId: string, taskId: string, data: ForceAcceptTaskRequest): Promise<TransitionResponse> {
    return fetchApi('/api/runs/' + runId + '/tasks/' + taskId + '/force-accept', {
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

  getRepoBranches(repoName: string, params?: { pattern?: string; include_remote?: boolean }): Promise<BranchesListResponse> {
    const sp = new URLSearchParams();
    if (params?.pattern) sp.set('pattern', params.pattern);
    if (params?.include_remote !== undefined) sp.set('include_remote', String(params.include_remote));
    const qs = sp.toString();
    return fetchApi('/api/repos/' + repoName + '/branches' + (qs ? '?' + qs : ''));
  },

  getRepoStats(repoName: string): Promise<RepoStatsResponse> {
    return fetchApi('/api/repos/' + repoName + '/stats');
  },

  addRepo(body: { url?: string; path?: string }): Promise<RepoResponse> {
    return fetchApi('/api/repos', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  removeRepo(name: string): Promise<void> {
    return fetchApi('/api/repos/' + name, { method: 'DELETE' });
  },

  fetchModelProfiles(): Promise<ModelProfileInfo[]> {
    return fetchApi('/api/model-profiles');
  },

  fetchAgentRunnerModelDefaults(runnerType: string): Promise<AgentRunnerModelDefaults> {
    return fetchApi('/api/agent-runners/' + encodeURIComponent(runnerType) + '/model-profile-defaults');
  },

  saveAgentRunnerModelDefaults(
    runnerType: string,
    defaults: AgentRunnerModelDefaults,
  ): Promise<AgentRunnerModelDefaults> {
    return fetchApi('/api/agent-runners/' + encodeURIComponent(runnerType) + '/model-profile-defaults', {
      method: 'PUT',
      body: JSON.stringify(defaults),
    });
  },
};

export function recoverRun(runId: string, data: RecoverRequest): Promise<RecoverResponse> {
  return api.recoverRun(runId, data);
}

export function approveStep(runId: string, stepId: string, data: { approved_by: string; comment?: string }): Promise<unknown> {
  return api.approveStep(runId, stepId, data);
}

export function transitionBack(runId: string, data: { target_step_index: number; reason?: string }): Promise<RunResponse> {
  return api.transitionBack(runId, data);
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

export function validateRoutine(yamlContent: string): Promise<ValidationResult> {
  return api.validateRoutine(yamlContent);
}

export function fetchModelProfiles(): Promise<ModelProfileInfo[]> {
  return api.fetchModelProfiles();
}

export function fetchAgentRunnerModelDefaults(runnerType: string): Promise<AgentRunnerModelDefaults> {
  return api.fetchAgentRunnerModelDefaults(runnerType);
}

export function saveAgentRunnerModelDefaults(
  runnerType: string,
  defaults: AgentRunnerModelDefaults,
): Promise<AgentRunnerModelDefaults> {
  return api.saveAgentRunnerModelDefaults(runnerType, defaults);
}
