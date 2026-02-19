export interface GlobalConfig {
  db_path: string;
  active_agent_types: string[];
  max_recent_runs: number;
  dashboard_refresh_interval_seconds: number;
  dashboard_max_recent_runs: number;
  agents_openhands_url: string | null;
  agents_default_type: string | null;
}
