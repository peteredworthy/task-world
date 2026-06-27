# Dynamic Graph Final Check Dispatch Dogfood

This run validates dynamic graph scheduler/driver reconciliation after the final check becomes ready. The planner, worker, verifier, and corrective verifier paths are represented in the graph handoff: planner output creates the work, worker leases execute ready nodes, verifier feedback can introduce corrective verifier work, and the scheduler must reconcile newly ready nodes without losing lease ownership or completion state.

The dogfood focus is the late invariant transition: once final blockers clear, the scheduler ready nodes include the final check, the driver dispatches it under normal leases, and the result is recorded as final check dispatch/result evidence rather than being skipped or stranded behind stale blocker state.
