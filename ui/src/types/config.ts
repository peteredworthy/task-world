export interface GlobalConfig {
  dashboard_refresh_interval_seconds: number;
  dashboard_max_recent_runs: number;
  default_execution_mode: 'legacy' | 'graph';
  agents_openhands_url: string | null;
  agents_default_type: string | null;
}
