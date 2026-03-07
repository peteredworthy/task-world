import type { ModelProfile } from './modelProfiles';

export interface Agent {
  id: string;
  name: string;
  system_prompt: string;
  default_prompt: string;
  model_profile: ModelProfile;
  created_at: string;
  updated_at: string;
}

export interface CreateAgentRequest {
  name: string;
  system_prompt: string;
  default_prompt?: string;
  model_profile?: ModelProfile;
}

export interface UpdateAgentRequest {
  name?: string;
  system_prompt?: string;
  default_prompt?: string;
  model_profile?: ModelProfile;
}
