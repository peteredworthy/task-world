import type { AgentType } from './enums';

export interface AgentConfigField {
  name: string;
  field_type: string;
  required: boolean;
  default: unknown;
  description: string;
  options: string[] | null;
}

export interface AgentOption {
  agent_type: AgentType;
  name: string;
  title: string;
  description: string;
  available: boolean;
  detail: string;
  install_hint: string;
  config_schema: AgentConfigField[];
}
