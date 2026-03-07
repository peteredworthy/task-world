import { fetchApi } from '../api/client';
import type { Agent, CreateAgentRequest, UpdateAgentRequest } from '../types/agents';

export function fetchAgents(): Promise<Agent[]> {
  return fetchApi('/api/agents');
}

export function fetchAgent(agentId: string): Promise<Agent> {
  return fetchApi('/api/agents/' + agentId);
}

export function createAgent(req: CreateAgentRequest): Promise<Agent> {
  return fetchApi('/api/agents', {
    method: 'POST',
    body: JSON.stringify(req),
  });
}

export function updateAgent(agentId: string, req: UpdateAgentRequest): Promise<Agent> {
  return fetchApi('/api/agents/' + agentId, {
    method: 'PUT',
    body: JSON.stringify(req),
  });
}

export function deleteAgent(agentId: string): Promise<void> {
  return fetchApi('/api/agents/' + agentId, { method: 'DELETE' });
}

export function resetAgentPrompt(agentId: string): Promise<Agent> {
  return fetchApi('/api/agents/' + agentId + '/reset-prompt', { method: 'POST' });
}
