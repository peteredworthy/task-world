export interface RepoResponse {
  name: string;
  path: string;
  default_branch: string;
}

export interface ReposListResponse {
  repos: RepoResponse[];
}

export interface BranchResponse {
  name: string;
  is_remote: boolean;
  commit: string;
}

export interface BranchesListResponse {
  branches: BranchResponse[];
  total: number;
  truncated: boolean;
}

export interface BranchCountResponse {
  count: number;
  pattern: string;
}

export interface ProjectRoutineResponse {
  id: string;
  name: string;
  description: string | null;
  source: string;
  path: string;
  commit: string;
  has_scaffolding: boolean;
  config: Record<string, unknown>;
}

export interface ProjectRoutinesListResponse {
  routines: ProjectRoutineResponse[];
  branch: string;
  commit: string;
}
