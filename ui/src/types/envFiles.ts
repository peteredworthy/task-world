export interface EnvFile {
  path: string;
  masked_value: string;
  key: string;
}

export interface EnvSnapshot {
  id: string;
  timestamp: string;
  agent: string;
  files: EnvFile[];
}

export interface EnvDefaultTarget {
  target_path: string;
}
