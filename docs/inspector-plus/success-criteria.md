# Success Criteria: inspector-plus

- In the UI inspector panel, the same task information shown in the detailed task view is present (requirements checklist, attempt history, failure/verification summaries, agent logs/output, and prompt content), verified by comparing the inspector against the expanded `TaskDetailCard` view for the same task.
- Agent output and prompt content in the inspector are shown via a popup/modal interaction (not inline expansion), verified by clicking the inspector controls and observing a modal overlay with the content.
- Using the chrome MCP to inspect the dashboard with the inspector open at its narrow width (e.g., ~340px), the inspector content fits without horizontal scrolling and key sections remain readable; any density adjustments are reflected in the inspector layout styles.
