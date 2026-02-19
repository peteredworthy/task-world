# Step 10: Env File Management UI (UI-ENV-FILE-MANAGEMENT)

This step adds an `EnvFilesPanel` to `RunDetail` that lists the run's current env files (with
masked values), shows snapshot history, and provides revert and copy-back actions. The backend
env file endpoints already exist and are tested. This step adds five client functions, five hooks,
new types, and the `EnvFilesPanel` component. The panel is only shown when `run.env_file_specs`
is non-empty.

## Intent Verification
**Original Intent**: `docs/bug-removal/intent.md` — "`EnvFilesPanel` renders current env files and snapshot history with revert and copy-back actions; shown in `RunDetail` when `env_file_specs` is non-empty"
**Functionality to Produce**:
- `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget` types in `ui/src/types/`
- Five client functions in `ui/src/api/client.ts`
- Five hooks in `ui/src/hooks/useApi.ts`
- `EnvFilesPanel` at `ui/src/components/detail/EnvFilesPanel.tsx`
- `RunDetail` mounts `EnvFilesPanel` when `run.env_file_specs` is non-empty

**Final Verification Criteria**:
- `npx tsc --noEmit` passes with no type errors
- `EnvFilesPanel.tsx` exists at the expected path
- All five client functions and five hooks exported from their respective files
- Vitest test for `EnvFilesPanel` passes

---

## Task 1: Add env file TypeScript types and client functions
**Description**:
Add `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget` types and all five env file client functions
to the frontend.

**Implementation Plan (Do These Steps)**
- [ ] Add types to `ui/src/types/` (create `types/envFiles.ts` or extend existing):
```typescript
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
```
- [ ] Open `ui/src/api/client.ts` and add the five functions:
```typescript
export async function getEnvFiles(runId: string): Promise<EnvFile[]> {
  const response = await fetch(`/api/runs/${runId}/env-files`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

export async function getEnvSnapshots(runId: string): Promise<EnvSnapshot[]> {
  const response = await fetch(`/api/runs/${runId}/env-snapshots`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

export async function getEnvDefaultTarget(runId: string): Promise<EnvDefaultTarget> {
  const response = await fetch(`/api/runs/${runId}/env-default-target`);
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json();
}

export async function revertEnvSnapshot(runId: string, snapshotId: string): Promise<void> {
  const response = await fetch(`/api/runs/${runId}/env-snapshots/${snapshotId}/revert`, {
    method: 'POST',
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
}

export async function copyBackEnvFiles(runId: string, targetPath: string): Promise<void> {
  const response = await fetch(`/api/runs/${runId}/env-copy-back`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target_path: targetPath }),
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
}
```

**References**
- `docs/bug-removal/step-10-plan.md` — Task 1 and Task 2 descriptions
- `docs/bugs/UI-ENV-FILE-MANAGEMENT.md`
- Backend: existing env file endpoints in `src/orchestrator/api/routers/runs.py`
- Security: masked values are a backend guarantee; frontend must not unmask or log raw values

**Constraints**
- [ ] Only `ui/src/types/` (new file) and `ui/src/api/client.ts` should be changed in this task
- [ ] Do not attempt to display unmasked env values; always show `masked_value` only

**Functionality (Expected Outcomes)**
- [ ] `EnvFile`, `EnvSnapshot`, `EnvDefaultTarget` types exported from `ui/src/types/`
- [ ] All five client functions exported from `ui/src/api/client.ts`

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0

---

## Task 2: Add five env file hooks to useApi.ts
**Description**:
Add three query hooks (`useEnvFiles`, `useEnvSnapshots`, `useEnvDefaultTarget`) and two mutation
hooks (`useRevertEnvSnapshot`, `useCopyBackEnvFiles`) to `ui/src/hooks/useApi.ts`.

**Implementation Plan (Do These Steps)**
- [ ] Open `ui/src/hooks/useApi.ts`
- [ ] Add the three query hooks:
```typescript
export function useEnvFiles(runId: string) {
  return useQuery({
    queryKey: ['envFiles', runId],
    queryFn: () => getEnvFiles(runId),
  });
}

export function useEnvSnapshots(runId: string) {
  return useQuery({
    queryKey: ['envSnapshots', runId],
    queryFn: () => getEnvSnapshots(runId),
  });
}

export function useEnvDefaultTarget(runId: string) {
  return useQuery({
    queryKey: ['envDefaultTarget', runId],
    queryFn: () => getEnvDefaultTarget(runId),
  });
}
```
- [ ] Add the two mutation hooks:
```typescript
export function useRevertEnvSnapshot(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (snapshotId: string) => revertEnvSnapshot(runId, snapshotId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['envFiles', runId] });
      queryClient.invalidateQueries({ queryKey: ['envSnapshots', runId] });
    },
  });
}

export function useCopyBackEnvFiles(runId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (targetPath: string) => copyBackEnvFiles(runId, targetPath),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['envFiles', runId] });
    },
  });
}
```

**References**
- `docs/bug-removal/step-10-plan.md` — Task 3 description

**Constraints**
- [ ] Only `ui/src/hooks/useApi.ts` should be changed in this task

**Functionality (Expected Outcomes)**
- [ ] All five hooks exported from `ui/src/hooks/useApi.ts`
- [ ] Mutation hooks invalidate env-related queries on success

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `grep -n "useEnvFiles\|useEnvSnapshots\|useEnvDefaultTarget\|useRevertEnvSnapshot\|useCopyBackEnvFiles" ui/src/hooks/useApi.ts` shows all five

---

## Task 3: Create EnvFilesPanel, mount in RunDetail, write Vitest test
**Description**:
Create the `EnvFilesPanel` component with current files list, snapshot history table, and action
buttons with confirmation dialogs. Mount it in `RunDetail` when `run.env_file_specs` is non-empty.
Write a Vitest test.

**Implementation Plan (Do These Steps)**
- [ ] Create `ui/src/components/detail/EnvFilesPanel.tsx`:
```typescript
interface EnvFilesPanelProps {
  runId: string;
}

export function EnvFilesPanel({ runId }: EnvFilesPanelProps) {
  const { data: envFiles } = useEnvFiles(runId);
  const { data: snapshots } = useEnvSnapshots(runId);
  const { data: defaultTarget } = useEnvDefaultTarget(runId);
  const revertMutation = useRevertEnvSnapshot(runId);
  const copyBackMutation = useCopyBackEnvFiles(runId);

  const [revertingId, setRevertingId] = useState<string | null>(null);
  const [copyBackPath, setCopyBackPath] = useState<string>('');

  return (
    <div>
      <h3>Current Env Files</h3>
      {envFiles?.map((f) => (
        <div key={f.path}>{f.path}: {f.masked_value}</div>
      ))}

      <h3>Snapshot History</h3>
      <table>
        <thead><tr><th>Time</th><th>Agent</th><th>Actions</th></tr></thead>
        <tbody>
          {snapshots?.map((snap) => (
            <tr key={snap.id}>
              <td>{snap.timestamp}</td>
              <td>{snap.agent}</td>
              <td>
                <button onClick={() => setRevertingId(snap.id)}>Revert</button>
                <button onClick={() => setCopyBackPath(defaultTarget?.target_path ?? '')}>Copy Back</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Revert confirmation dialog */}
      {revertingId && (
        <ConfirmationDialog
          title="Revert env snapshot?"
          onConfirm={() => { revertMutation.mutate(revertingId); setRevertingId(null); }}
          onCancel={() => setRevertingId(null)}
        />
      )}

      {/* Copy-back path confirmation dialog */}
      {copyBackPath !== '' && (
        <ConfirmationDialog
          title={`Copy env files back to ${copyBackPath}?`}
          onConfirm={() => { copyBackMutation.mutate(copyBackPath); setCopyBackPath(''); }}
          onCancel={() => setCopyBackPath('')}
        />
      )}
    </div>
  );
}
```
- [ ] Open `ui/src/pages/RunDetail.tsx`
- [ ] Import `EnvFilesPanel` and mount it conditionally:
```typescript
{run.env_file_specs && run.env_file_specs.length > 0 && (
  <EnvFilesPanel runId={run.id} />
)}
```
- [ ] Write a Vitest test in `ui/src/components/detail/__tests__/EnvFilesPanel.test.tsx`:
```typescript
const mockSnapshots = [
  { id: 'snap-1', timestamp: '2026-01-01T00:00:00Z', agent: 'claude', files: [] },
];

test('renders snapshot table with revert button', () => {
  render(<EnvFilesPanel runId="run-1" />); // mock useEnvSnapshots to return mockSnapshots
  expect(screen.getByText(/2026-01-01/i)).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /revert/i })).toBeInTheDocument();
});
```
- [ ] Run `npx vitest run` and confirm all tests pass

**References**
- `docs/bug-removal/step-10-plan.md` — Task 4, Task 5, Task 6 descriptions
- `docs/bug-removal/architecture.md` — "New Components: EnvFilesPanel"
- Security note: masked values only; no plaintext secrets in the UI

**Constraints**
- [ ] New file: `EnvFilesPanel.tsx`; modified file: `RunDetail.tsx`; new test file
- [ ] Panel must be hidden when `run.env_file_specs` is empty or null

**Functionality (Expected Outcomes)**
- [ ] `EnvFilesPanel.tsx` exists at `ui/src/components/detail/EnvFilesPanel.tsx`
- [ ] Current files section shows masked values
- [ ] Snapshot history table shows timestamps and action buttons
- [ ] Revert action shows confirmation dialog before calling the API
- [ ] Copy-back action shows path confirmation dialog before calling the API
- [ ] Vitest test for `EnvFilesPanel` passes

**Final Verification (Proof of Completion)**
⚠️ DO NOT CHECK ANY OF THESE UNTIL IMPLEMENTATION IS COMPLETE
- [ ] `npx tsc --noEmit` exits 0
- [ ] `npx vitest run` exits 0 (all tests pass including the new EnvFilesPanel test)
- [ ] File exists: `ui/src/components/detail/EnvFilesPanel.tsx`
