import type { ModelProfile } from './generated-enums';

export type { ModelProfile };

export interface ModelProfileInfo {
  name: ModelProfile;
  description: string;
}

export interface RunnerProfileDefaults {
  runner_type: string;
  profiles: Partial<Record<ModelProfile, string>>;
}
