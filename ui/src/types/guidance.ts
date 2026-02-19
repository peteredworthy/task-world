export interface GuidanceResponse {
  task_id: string;
  prompt: string;
  phase: string;
  mcp_url: string;
  expected_actions: string[];
}
