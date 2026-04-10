# Implementation Slices: Phase 6 - Web UI

**Goal:** Implement React-based web dashboard for monitoring and controlling runs.

**End state:** Can view runs, tasks, checklists; receive real-time updates; trigger actions.

**Prerequisites:** Phase 4 complete (API), Phase 5 complete (agents).

---

## Slice 6.1: React Application Setup

### Goal
Set up React application with TypeScript, routing, and API client.

### Deliverables

```
ui/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── api/
│   │   └── client.ts      # API client
│   ├── hooks/
│   │   └── useApi.ts      # Data fetching hooks
│   └── components/
│       └── Layout.tsx
└── tests/
    └── setup.ts
```

### Architecture Constraints

1. **Vite for builds** - Fast development, good production builds
2. **React Router for navigation** - SPA routing
3. **TanStack Query for data** - Caching, refetching, optimistic updates
4. **Tailwind for styling** - Utility-first CSS
5. **No component library initially** - Build what we need

### Implementation Steps

1. Initialize project:
   ```bash
   npm create vite@latest ui -- --template react-ts
   cd ui
   npm install react-router-dom @tanstack/react-query tailwindcss
   ```

2. Create API client `src/api/client.ts`:
   ```typescript
   const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000';

   // JWT token for authenticated requests (set via VITE_AUTH_TOKEN env var
   // or read from server output when AUTH_DISABLED=false).
   let authToken: string | null = import.meta.env.VITE_AUTH_TOKEN || null;

   export function setAuthToken(token: string | null) {
     authToken = token;
   }

   export function getAuthToken(): string | null {
     return authToken;
   }

   export async function fetchApi<T>(
     path: string,
     options?: RequestInit
   ): Promise<T> {
     const headers: Record<string, string> = {
       'Content-Type': 'application/json',
       ...(options?.headers as Record<string, string>),
     };
     if (authToken) {
       headers['Authorization'] = `Bearer ${authToken}`;
     }

     const response = await fetch(`${API_BASE}${path}`, {
       ...options,
       headers,
     });

     if (!response.ok) {
       const error = await response.json();
       throw new Error(error.error || 'API request failed');
     }

     return response.json();
   }
   
   // Typed API functions
   export const api = {
     routines: {
       list: () => fetchApi<RoutineListResponse>('/api/routines'),
       get: (id: string) => fetchApi<RoutineDetail>(`/api/routines/${id}`),
     },
     runs: {
       list: (projectId?: string) => 
         fetchApi<RunListResponse>(`/api/runs${projectId ? `?project_id=${projectId}` : ''}`),
       get: (id: string) => fetchApi<RunResponse>(`/api/runs/${id}`),
       create: (data: CreateRunRequest) => 
         fetchApi<RunResponse>('/api/runs', { method: 'POST', body: JSON.stringify(data) }),
       start: (id: string) => 
         fetchApi<RunResponse>(`/api/runs/${id}/start`, { method: 'POST' }),
       delete: (id: string) => 
         fetchApi<void>(`/api/runs/${id}`, { method: 'DELETE' }),
     },
     tasks: {
       get: (runId: string, taskId: string) =>
         fetchApi<TaskDetail>(`/api/runs/${runId}/tasks/${taskId}`),
       updateChecklist: (runId: string, taskId: string, reqId: string, data: ChecklistUpdate) =>
         fetchApi<ChecklistItem>(`/api/runs/${runId}/tasks/${taskId}/checklist/${reqId}`, {
           method: 'PATCH', body: JSON.stringify(data)
         }),
     },
   };
   ```

3. Create hooks `src/hooks/useApi.ts`:
   ```typescript
   import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
   import { api } from '../api/client';
   
   export function useRuns(projectId?: string) {
     return useQuery({
       queryKey: ['runs', projectId],
       queryFn: () => api.runs.list(projectId),
       refetchInterval: 5000, // Poll every 5s
     });
   }
   
   export function useRun(runId: string) {
     return useQuery({
       queryKey: ['run', runId],
       queryFn: () => api.runs.get(runId),
       refetchInterval: 2000, // More frequent for active run
     });
   }
   
   export function useStartRun() {
     const queryClient = useQueryClient();
     return useMutation({
       mutationFn: (runId: string) => api.runs.start(runId),
       onSuccess: () => {
         queryClient.invalidateQueries({ queryKey: ['runs'] });
       },
     });
   }
   ```

4. Create basic layout and routes

### Verification

#### E2E Test
```bash
cd ui && npm run dev &
# Wait for server
curl http://localhost:5173  # Should return HTML
```

### Definition of Done
- [ ] Vite + React + TypeScript works
- [ ] API client typed
- [ ] TanStack Query hooks created
- [ ] Basic routing works

---

## Slice 6.2: Dashboard View

### Goal
Implement main dashboard showing run list with status, filters, and actions.

### Deliverables

```
ui/src/
├── pages/
│   └── Dashboard.tsx
├── components/
│   ├── RunCard.tsx
│   ├── RunFilters.tsx
│   ├── StatusBadge.tsx
│   └── EmptyState.tsx
```

### Architecture Constraints

1. **Show active + recent** - Filter by recency (1h, 4h, 24h, 1 week)
2. **Expandable rows** - Click to expand and see steps
3. **Real-time updates** - Via polling initially, WebSocket later
4. **Responsive** - Works on mobile

### Implementation: RunCard Component

```typescript
interface RunCardProps {
  run: RunResponse;
  expanded: boolean;
  onToggle: () => void;
  onStart: () => void;
  onDelete: () => void;
}

function RunCard({ run, expanded, onToggle, onStart, onDelete }: RunCardProps) {
  return (
    <div className="border rounded-lg p-4 bg-white shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <StatusIndicator status={run.status} />
          <div>
            <h3 className="font-medium">{run.routine_id || 'Embedded routine'}</h3>
            <p className="text-sm text-gray-500">
              {run.project_id} • {formatRelativeTime(run.updated_at)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {run.status === 'draft' && (
            <button onClick={onStart} className="btn-primary">Start</button>
          )}
          <button onClick={onToggle} className="btn-icon">
            {expanded ? <ChevronUp /> : <ChevronDown />}
          </button>
        </div>
      </div>
      
      {expanded && (
        <div className="mt-4 border-t pt-4">
          <StepTimeline steps={run.steps} />
        </div>
      )}
    </div>
  );
}
```

### Verification

#### E2E Test
1. Start API server with test data
2. Load dashboard
3. Verify runs displayed
4. Filter by status
5. Expand/collapse works

### Definition of Done
- [ ] Dashboard shows runs
- [ ] Status colors correct
- [ ] Filters work
- [ ] Expand/collapse works
- [ ] Start/delete actions work

---

## Slice 6.3: Run Detail View

### Goal
Implement detailed view of a single run with steps, tasks, checklist, and attempt history.

### Deliverables

```
ui/src/
├── pages/
│   └── RunDetail.tsx
├── components/
│   ├── StepAccordion.tsx
│   ├── TaskCard.tsx
│   ├── ChecklistTable.tsx
│   ├── AttemptHistory.tsx
│   └── GradeDisplay.tsx
```

### Implementation: ChecklistTable Component

```typescript
interface ChecklistTableProps {
  checklist: ChecklistItem[];
  onUpdate: (reqId: string, status: ChecklistStatus, note?: string) => void;
  readonly?: boolean;
}

function ChecklistTable({ checklist, onUpdate, readonly }: ChecklistTableProps) {
  return (
    <table className="w-full">
      <thead>
        <tr className="text-left text-sm text-gray-500">
          <th className="w-12">Status</th>
          <th>Requirement</th>
          <th className="w-20">Priority</th>
          <th className="w-16">Grade</th>
        </tr>
      </thead>
      <tbody>
        {checklist.map((item) => (
          <tr key={item.req_id} className="border-t">
            <td>
              <StatusIcon status={item.status} />
            </td>
            <td className="py-2">
              <span className={item.status === 'done' ? 'line-through text-gray-400' : ''}>
                {item.desc}
              </span>
              {item.note && (
                <p className="text-sm text-gray-500 mt-1">{item.note}</p>
              )}
            </td>
            <td>
              <PriorityBadge priority={item.priority} />
            </td>
            <td>
              {item.grade && <GradeBadge grade={item.grade} />}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

### Verification

#### E2E Test
1. Navigate to run detail
2. Verify steps/tasks displayed
3. Checklist shows correct status
4. Grade colors correct
5. Attempt history visible

### Definition of Done
- [ ] Run detail page works
- [ ] Steps expandable
- [ ] Checklist displays correctly
- [ ] Grades shown with colors
- [ ] Attempt history visible

---

## Slice 6.4: Agent Guidance Panel

### Goal
Implement panel that guides users starting external agents.

### Deliverables

```
ui/src/components/
├── AgentGuidancePanel.tsx
├── PromptCopyBox.tsx
└── WaitingIndicator.tsx
```

### Implementation

```typescript
interface AgentGuidancePanelProps {
  run: RunResponse;
  task: TaskDetail;
  prompt: BuilderPrompt;
  mcpUrl: string;
  authToken: string | null;  // JWT token when auth is enabled, null when disabled
  onStarted: () => void;
  onCancel: () => void;
}

function AgentGuidancePanel({
  run, task, prompt, mcpUrl, authToken, onStarted, onCancel
}: AgentGuidancePanelProps) {
  const [copied, setCopied] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [elapsed, setElapsed] = useState(0);

  // Timer for elapsed time
  useEffect(() => {
    if (!waiting) return;
    const interval = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(interval);
  }, [waiting]);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(prompt.user);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleStarted = () => {
    setWaiting(true);
    onStarted();
  };

  return (
    <div className="border rounded-lg p-6 bg-gray-50">
      <h3 className="font-medium mb-4">Start Your Agent</h3>

      <div className="mb-4">
        <label className="text-sm text-gray-600">Copy this prompt:</label>
        <div className="relative mt-1">
          <pre className="bg-white border rounded p-3 text-sm overflow-auto max-h-48">
            {prompt.user}
          </pre>
          <button
            onClick={handleCopy}
            className="absolute top-2 right-2 btn-icon"
          >
            {copied ? <Check /> : <Copy />}
          </button>
        </div>
      </div>

      <div className="mb-4">
        <label className="text-sm text-gray-600">MCP Server URL:</label>
        <code className="block bg-white border rounded p-2 mt-1">
          {mcpUrl}
        </code>
      </div>

      {authToken && (
        <div className="mb-4">
          <label className="text-sm text-gray-600">Authentication:</label>
          <p className="text-sm text-gray-500 mt-1">
            Include this header with all API/MCP requests:
          </p>
          <code className="block bg-white border rounded p-2 mt-1 break-all">
            Authorization: Bearer {authToken}
          </code>
          <p className="text-xs text-gray-400 mt-1">
            For WebSocket connections, append <code>?token={authToken}</code> to the URL.
          </p>
        </div>
      )}

      {waiting ? (
        <div className="text-center py-4">
          <Spinner />
          <p className="mt-2">Waiting for agent connection...</p>
          <p className="text-sm text-gray-500">Elapsed: {formatDuration(elapsed)}</p>
          <button onClick={onCancel} className="mt-4 btn-secondary">
            Cancel
          </button>
        </div>
      ) : (
        <button onClick={handleStarted} className="btn-primary w-full">
          I've Started the Agent
        </button>
      )}
    </div>
  );
}
```

### Definition of Done
- [ ] Prompt displayed and copyable
- [ ] MCP URL shown
- [ ] Auth token shown when auth is enabled (with Bearer header and WebSocket query param instructions)
- [ ] Waiting state with timer
- [ ] Cancel button works

---

## Slice 6.5: WebSocket Integration

### Goal
Connect to WebSocket for real-time updates instead of polling.

### Deliverables

```
ui/src/
├── hooks/
│   └── useWebSocket.ts
└── context/
    └── WebSocketContext.tsx
```

### Implementation

```typescript
function useRunWebSocket(runId: string) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    // Append ?token= for WebSocket auth when auth is enabled
    const token = getAuthToken();
    const wsBase = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';
    const tokenParam = token ? `?token=${token}` : '';
    const ws = new WebSocket(`${wsBase}/ws/runs/${runId}${tokenParam}`);

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);

      // Update query cache with new data
      if (message.type === 'task_status_changed') {
        queryClient.invalidateQueries({ queryKey: ['run', runId] });
      }
    };

    return () => ws.close();
  }, [runId, queryClient]);

  return { connected };
}
```

### Definition of Done
- [ ] WebSocket connects
- [ ] Events trigger cache invalidation
- [ ] Connection status displayed
- [ ] Graceful disconnect handling

---

## Phase 6 Milestone Verification

```bash
# Build UI
cd ui && npm run build

# Start API
uv run uvicorn orchestrator.api.app:create_app --factory &

# Serve UI (production build)
npx serve ui/dist &

# Open browser to http://localhost:3000

# Manual verification:
# 1. Dashboard loads
# 2. Can create run
# 3. Can view run detail
# 4. Status updates in real-time
# 5. Agent guidance panel works
```

If UI works, Phase 6 is complete. Proceed to Phase 7.
