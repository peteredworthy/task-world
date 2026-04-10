export type ModelProfile = 'architect' | 'designer' | 'coder' | 'summarizer';

export interface ModelProfileInfo {
  name: ModelProfile;
  description: string;
}

export interface RunnerProfileDefaults {
  runner_type: string;
  profiles: Partial<Record<ModelProfile, string>>;
}
