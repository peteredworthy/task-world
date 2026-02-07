export type RunStatus = 'draft' | 'active' | 'paused' | 'completed' | 'failed';

export type TaskStatus = 'pending' | 'building' | 'verifying' | 'completed' | 'failed';

export type ChecklistStatus = 'open' | 'done' | 'not_applicable' | 'blocked';

export type Priority = 'critical' | 'expected' | 'nice';

export type AgentType = string;
