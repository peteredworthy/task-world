import type { ModelProfile } from './generated-enums';

export type { ModelProfile };

export interface ModelProfileInfo {
  name: ModelProfile;
  description: string;
}

export interface AgentRunnerModelDefaults {
  agent_runner_type: string;
  model_profile_defaults: Partial<Record<ModelProfile, string>>;
}
