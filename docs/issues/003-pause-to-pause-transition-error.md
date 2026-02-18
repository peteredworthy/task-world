# Issue 003: Pausing Displays Banner Error About Paused-to-Paused Transition

## Problem

When a user clicks the pause button on a running run, the run pauses successfully but the frontend displays an error banner with a message like:

```
Cannot transition from paused to paused
```

This appears to be a race condition where the pause request is sent multiple times, or the UI sends a pause request after the run has already transitioned to the paused state (e.g. due to a WebSocket update arriving before the API response).

## Expected Behavior

- Clicking pause should pause the run and show no error.
- If the run is already paused, a subsequent pause request should either be a no-op or silently ignored — not surface an error to the user.

## Root Cause Investigation

### Likely cause: Double-fire of pause action

The frontend may be sending the pause request and then, before the response arrives, receiving a WebSocket event that updates the run status to `paused`. If the UI re-renders with the new status and the user's click handler or a follow-up effect fires again, a second `POST /api/runs/{id}/pause` is sent against an already-paused run.

**Check:** `ui/src/components/` — how is the pause button wired? Does it disable itself after the first click? Does it check current run status before sending?

**Check:** `ui/src/hooks/useWebSocket.ts` — does a `run_status_changed` event trigger a re-render that could cause a duplicate pause call?

### Likely cause: Backend returns 4xx for idempotent operation

The backend transition logic likely rejects a `paused → paused` transition as invalid, returning an error response (likely HTTP 409 Conflict based on observed behavior with the API). The frontend then surfaces this error in a banner.

**Check:** `workflow/transitions.py` or `workflow/engine.py` — does the pause transition handler reject same-state transitions?

**Check:** `api/routers/runs.py` — what HTTP status code is returned for an invalid pause transition? How does the frontend error handler display it?

## Fix Options

### Option A: Backend — make pause idempotent

If the run is already paused, return a success response (200) instead of an error. This is the most robust fix since it handles all client-side race conditions without requiring frontend changes.

```python
# In the pause handler:
if run.status == RunStatus.PAUSED:
    return {"status": "already_paused"}  # 200, not 409
```

### Option B: Frontend — prevent duplicate requests

- Disable the pause button immediately on click (optimistic UI).
- Check `run.status` before sending the pause request.
- Suppress error banners for "already in target state" errors.

### Option C: Both (Recommended)

Apply both fixes for defense in depth. The backend should be idempotent for pause/resume operations, and the frontend should prevent unnecessary duplicate requests.

## Severity

**Low** — the run pauses correctly; this is a cosmetic error banner that may confuse users into thinking the pause failed.
