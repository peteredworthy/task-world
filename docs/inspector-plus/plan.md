# Plan: inspector-plus

**Status (April 2026):** Steps 1–2 complete; step 3 outstanding.

1. ~~Review TaskDetailCard sections and identify task info that must be mirrored in InspectorPanel.~~ ✅
2. ~~Update InspectorPanel to include missing task info (event timeline/clarification cards) and adjust layout density for the narrow inspector width.~~ ✅ Event timeline is implemented in `InspectorPanel.tsx`; clarification history rendered inline in events section.
3. Verify the inspector layout at ~340px width using the Chrome MCP and make any final spacing tweaks. **OUTSTANDING** — visual verification not yet done; no dedicated clarifications tab exists.
