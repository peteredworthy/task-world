import type { AgentRunnerType } from './enums';

export interface AgentConfigField {
  name: string;
  field_type: string;
  required: boolean;
  default: unknown;
  description: string;
  options: string[] | null;
  allow_custom: boolean;
}

export interface QuotaBucket {
  label: string;
  remaining_pct: number | null;
  remaining_usd: number | null;
  resets_at: string | null;
}

export interface AgentRunnerQuota {
  balance_usd: number | null;
  balance_pct: number | null;
  max_balance_usd: number | null;
  label: string;
  supports_quota: boolean;
  breakdown: QuotaBucket[] | null;
  fetched_at: string | null;
}

export interface AgentRunnerOption {
  agent_runner_type: AgentRunnerType;
  name: string;
  title: string;
  description: string;
  available: boolean;
  detail: string;
  install_hint: string;
  config_schema: AgentConfigField[];
  quota: AgentRunnerQuota | null;
}
