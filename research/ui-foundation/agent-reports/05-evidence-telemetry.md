# Evidence and Telemetry Audit

## Purpose

Establish what evidence and telemetry the current implementation actually
produces, persists, attributes, and exposes. This audit covers workflow and graph
events, records, prompts, runner output and action traces, repository file-state
boundaries, artifacts, usage and cost facts, cross-run rollups, and detector
inputs. It verifies production producer wiring rather than treating accepted
schemas as proof that data exists.

This is a bounded Phase 1 report. Local keys `ET-*` are report-only references,
not canonical semantic IDs. Findings use these source-status terms:
`implemented`, `tested`, `documented-only`, `inferred`, and `unclear`.

## Scope inspected

Controls and source demands:

- `.superpowers/sdd/task-7-brief.md`
- `AGENTS.md`
- `docs/superpowers/specs/2026-07-23-ui-foundation-phase-0-3-design.md`
- `research/ui-foundation/catalog/scope.yaml`
- `research/ui-foundation/catalog/evidence.yaml`
- `research/ui-foundation/agent-reports/00-delegation-plan.md`
- `docs/jtbd/jobs.md`, `docs/jtbd/journeys.md`,
  `docs/jtbd/decision-information.md`, and
  `docs/jtbd/information-architecture.md`

Producer and storage paths:

- `src/orchestrator/db/access/event_store_v2.py`
- `src/orchestrator/db/access/activity_summaries.py`
- `src/orchestrator/db/orm/models.py`
- `src/orchestrator/workflow/events/types.py`
- `src/orchestrator/graph/models.py`
- `src/orchestrator/graph/_commands.py`
- `src/orchestrator/graph/projections.py`
- `src/orchestrator/graph_runtime/controller.py`
- `src/orchestrator/graph_runtime/store.py`
- `src/orchestrator/graph_runtime/dispatch.py`
- `src/orchestrator/graph_runtime/prompts.py`
- `src/orchestrator/graph_runtime/file_state.py`
- `src/orchestrator/graph/file_state.py`
- `src/orchestrator/artifacts/store.py`
- `src/orchestrator/artifacts/resolution.py`
- `src/orchestrator/runners/types.py`
- `src/orchestrator/runners/execution/usage.py`
- `src/orchestrator/runners/execution/attempt_store.py`
- `src/orchestrator/runners/execution/output_batcher.py`
- `src/orchestrator/runners/execution/phase_handler.py`
- `src/orchestrator/runners/costs.py`
- Claude CLI, Codex, and OpenHands runner parsers and execution adapters
- `src/orchestrator/runners/runtime/repetition_detector.py`
- `src/orchestrator/runners/runtime/nudger.py`
- `model_costs.yaml`

Readbacks and rollups:

- `src/orchestrator/api/routers/runs.py`
- `src/orchestrator/api/routers/graph.py`
- `src/orchestrator/api/routers/cost_rollup.py`
- `src/orchestrator/api/presenters/runs.py`
- `src/orchestrator/api/presenters/evidence_digest.py`
- `src/orchestrator/api/presenters/cost_rollup.py`
- `src/orchestrator/api/schemas/cost_rollup.py`
- `src/orchestrator/api/metrics.py`
- `scripts/cost_report.py`

Relevant tests were inspected as source evidence, especially event durability and
wiring, graph event storage, graph usage persistence, API and pure cost rollups,
cost records, runner usage extraction, output batching, prompt summaries and
hydration, artifact storage/API/GC, file-state capture/reporting, and repetition
detectors. No product test suite was run for this read-only audit; `tested` below
means a test exercises the cited behavior in source, not that this task freshly
executed that test.

## Key findings

### Evidence inventory and producer wiring

| Key | Evidence type and durable identity | Producer wiring | Attribution | Freshness and consistency | Status |
|---|---|---|---|---|---|
| ET-01 | Workflow event row: global `events_v2.position`; retry/import identity `(aggregate_id, version)` where `aggregate_id == run_id` | `SqliteEventStore.append` serializes every `WorkflowEvent`; `create_wired_event_store_v2` wires run/task projectors and the JSONL outbox; services, `AttemptStore`, and `OutputBatcher` call this path | `run_id` is mandatory; event-specific task, attempt, requirement, and node fields vary. `WorkflowEvent` has no event ID | DB row is authoritative and append-only. JSONL is a post-commit secondary output that can lag and is reconciled. Timestamp is producer time; global position is total DB order | implemented, tested |
| ET-02 | Graph event envelope: `event_id`, run-local `position`, event type/version, actor, causation/correlation, timestamp; DB identity is `(graph:<run_id>, version)` | `GraphController.handle_command` applies the command kernel and calls `GraphEventStore.append_events`; production dispatch uses controller commands, not direct appends | Run, actor, node/lease/execution/record IDs are carried where applicable. Graph and workflow streams are deliberately separate aggregates | Events, compact summaries, node-detail summaries, projection checkpoint, usage read model, outbox, and JSONL queue update in the graph transaction. Summary/checkpoint rows are disposable and rebuildable | implemented, tested |
| ET-03 | Accepted graph record: `record_id`, `record_type`, `producer_node_id`, `producer_port`, `created_at`, `graph_position`, `run_id`, schema version, typed payload | `GraphDispatchExecutor._submit_callback` creates candidate, verification, artifact-reference, and file-state records; check execution creates check-result records; graph commands validate and emit acceptance events | Strong run/node/port/record attribution; candidate, task region, attempt, evaluated records, and file-state citations are present for selected record types | `GraphEventStore` adds durable base fields at append time. Record is a boundary snapshot, not automatically current after later graph/file changes | implemented, tested |
| ET-04 | Graph prompt packet summary attached to runtime-start `node_state_changed`; no independent packet ID | `_execution_context` builds and sends the full prompt; `_acknowledge_start` persists `_prompt_summary_for_node` before runner execution. Production graph driver reaches this path | Run via stream; node, kind, role, task region, lease/generation/execution/base snapshot, tools, input ports, and compact bound records | Summary and start event share one graph position/timestamp. It proves assembly metadata, not byte-for-byte delivery or model ingestion | implemented, tested, partial |
| ET-05 | Legacy full builder/verifier/recovery prompt in `AttemptUpdated` and attempt columns; interaction-log row repeats prompt text | `PhaseHandler` calls `AttemptStore.store_attempt_prompt` before execution. `store_attempt_output` later upserts `InteractionLogArtifactModel` | Run/task/attempt and phase; interaction row adds runner type. No prompt hash or packet ID | Prompt write errors are caught and only debug-logged. Interaction row is a later best-effort direct DB write and can be missing even when attempt execution continues | implemented, tested, partial |
| ET-06 | Streamed runner output as ordered `agent_output` workflow events with global position and per-buffer `line_offset` | Production legacy and graph composition wire runner `on_output` through `OutputBatcher`; graph adds `node_id` | Run/task/attempt; graph adds node. No execution ID in `AgentOutputEvent` | Explicit final flush is wired. Lines are runner-dependent: raw NDJSON during CLI streaming, formatted OpenHands events, or other adapter output. There is no canonical transcript completeness marker | implemented, tested, partial |
| ET-07 | Structured action log: sequenced assistant/thinking/tool/result/error entries, tool-use/result IDs, parser timestamps, metrics, model/session/tools; tool output is truncated to 5 KiB with original length retained | Claude CLI, Codex, and OpenHands parsers populate `ExecutionResult.action_log`; legacy `PhaseHandler` persists it to attempts and interaction-log rows | Legacy run/task/attempt only. Builder and verifier logs are merged into one attempt sequence; phase identity is not attached to each entry | Parser coverage is carrier-specific and OpenHands parsing is best effort. Production graph dispatch extracts the action log for usage, then discards it; it is not persisted as a graph trace | implemented, tested, carrier-dependent; graph gap |
| ET-08 | Repository file-state record: `file-state-<execution_id>`, base and captured snapshot IDs, git commit/tree/ref, classified tracked/untracked/ignored/external paths, residue, rejection, cleanup lineage | Every successful graph agent submit calls `capture_file_state_boundary`; rejection is durably submitted and causes retry; checks execute against a prepared snapshot and produce check evidence | Run in event; producer node and execution; path classifications. The boundary is whole-worktree status, so a path is not necessarily caused solely by that node if writes overlap | Snapshot is immutable/restorable while its ref remains. The record is fresh only for that callback boundary. Normal producer does not emit diffstat or a content hash for ordinary tracked/untracked paths | implemented, tested |
| ET-09 | CAS artifact reference: content SHA-256 as artifact ID/hash plus size/media type/encoding/opaque URI | Check stdout/stderr over 16,384 bytes is put in the run project's CAS; the check record stores a 4,000-character tail and typed reference | CAS content is globally deduplicated within a project; authorization is established by finding the reference in that run's check-result events | Full blob is hash/size verified before API range read. Missing is 404, corrupt is 409. Publication locking coordinates append and GC | implemented, tested |
| ET-10 | Declared run-output artifact reference: graph record containing artifact ID/type/path URI/summary/source candidate ID | Worker submission translates static node payload `artifacts` declarations into records | Run/node/candidate via the accepted record | This path does not read the file, hash it, put it in CAS, or prove it exists. Generic references are not accepted by the CAS download endpoint | implemented declaration-to-record wiring, evidence integrity partial |
| ET-11 | Legacy interaction-log DB row keyed by stable run/task/attempt/runner/phase ID; prompt, final output, action-log JSON, optional cost-record FK | Only legacy `PhaseHandler` calls the `AttemptStore` upsert path. Production graph composition supplies output streaming but no equivalent interaction-log persistence | Strong legacy execution identity; no graph node/execution identity | Mutable upsert, direct commit, current-clock `created_at`, and swallowed write failure. It is not the content-addressed artifact store and has no dedicated public retrieval API | implemented, tested; graph gap |
| ET-12 | Immutable per-execution/model usage fact identified by `execution_id:usage_index` in `node_usage_recorded` | Graph agent executions that return an `ExecutionResult` call `extract_metrics_and_usage`; when the returned list is nonempty, `_run_agent` calls `GraphController.record_node_usage`. A raised runner exception jumps directly to `_agent_died` and bypasses extraction, even if provider work already consumed tokens. This is independent of the optional, unwired production `on_agent_usage` observer | Run stream, node ID/kind/role, profile, execution, usage index/count, model. Sub-agent usage becomes additional model facts but loses sub-agent ID/type | Command deduplicates by usage key; retries stale writes; graph projection and run usage read model are updated in the event transaction and can replay. Exact-zero/no-reported usage and exception-terminated usage emit no fact | implemented, tested return path; exception coverage gap |
| ET-13 | Legacy per-model usage in attempt/run JSON plus `CostRecordModel` keyed by run/task/attempt/runner/phase | `PhaseHandler` extracts and stores usage only after its runner call returns an `ExecutionResult`; returned unsuccessful results reach storage before the builder raises, but runner exceptions bypass output/metrics persistence. `AttemptStore` appends attempt telemetry then best-effort upserts the cost row | Run/task/attempt/phase/runner/model/mode; per-model list may include parent and sub-agent models | Attempt/run usage is event-projected; cost record is a mutable direct upsert with swallowed failures. Exception-terminated provider work can be unmetered. Legacy usage is not included in graph cross-run cost rollups | implemented, tested return path; exception coverage gap |
| ET-14 | Cross-run graph cost rollup rows grouped by day/node kind/model/profile/run | `GET /api/runs/cost-rollup` reads only persisted `graph:*` `node_usage_recorded` rows, joins runs, filters time/status/runner, and reduces them | Exact run/execution/model facts under each requested dimension; execution latency/actions counted once using run-scoped execution identity | Event timestamp defines UTC day. Input is capped at 100,000 facts and output at 1,000 groups. It excludes legacy cost records, exact-zero/no-reported executions, and exception-terminated executions without usage events | implemented, tested |
| ET-15 | Requirement-support freshness facts: fresh/stale support IDs, active requirement version, stale reason, unsupported flag | `support_evidence_recorded` and requirement revisions feed graph projection; planner packet computes freshness at dispatch | Requirement, version, support, and evidence IDs | A support becomes stale when inactive, missing an active requirement, or targeting a superseded version. The full freshness packet is sent to planners but only its key name, not its values, appears in prompt summary | implemented, tested in graph projection paths; exposure partial |
| ET-16 | Runner-local repetition/no-output inputs | OpenHands records normalized terminal commands, selected read-only tool actions, reasoning-prefix hashes, and an action count; CLI subprocess records time since output and nudge count | Process-local execution only | Values and detector verdicts are not durable telemetry. OpenHands pause degrades to generic exit/no-submit evidence; CLI nudge text or terminal error may appear in output/error events | implemented and unit-tested detector logic; durable detector evidence absent |

### Event ordering, identity, and readback

`events_v2.position` gives one durable global database order. Each workflow run
also has a run-local `version`, while each graph run has a separate run-local
version under `graph:<run_id>`. Graph `EventEnvelope.event_id` survives inside the
serialized event body, but workflow events have no corresponding event ID and the
SQL table has no `event_id` column. Consumers therefore must not treat graph
event ID, SQL position, aggregate version, record ID, execution ID, and attempt ID
as interchangeable.

`GET /api/runs/{run_id}/activity` merges all workflow events with only a selected
graph subset: rejected commands, accepted/rejected graph patches, deferrals,
verification pass/fail, and review-node creation. It orders that selection by
global SQL position and defaults to compact payloads. It is not the complete
graph ledger. `GET /api/runs/{run_id}/graph/events` is the run-local graph ledger,
with summary/full modes. A complete temporal chronology currently requires joining
the two namespaced streams by global SQL position; no public endpoint returns
that complete join.

Graph actor, causation, and correlation fields support mechanism tracing better
than workflow events. Temporal order alone is not causal proof. Candidate,
verification, and check records add explicit evaluated-record and file-state
citations, but those citations do not establish that a repository change caused
a grade or that a prompt omission caused a failure.

### Prompt, transcript, tool, and file boundaries

Legacy and graph execution have materially different evidence coverage:

| Boundary | Legacy execution | Graph execution | Missing or stale condition |
|---|---|---|---|
| Full prompt | Stored before each phase on the attempt | Built and sent but not stored | Legacy write can fail silently; graph cannot prove exact bytes or truncation after the fact |
| Packet identity | Attempt/phase only | Node + lease/generation/execution/base snapshot in compact start summary | Neither has a packet ID, content hash, parent directive ID, or delivery acknowledgement from the model |
| Bound input records | Not a generic prompt contract | All bound IDs in `input_ports`; compact metadata for at most 10 records per port | Summary does not state that compact records were capped at 10; missing records are marked only when assembly sees an unresolved ID |
| Omission/reference policy | No normalized field | `structured_json`, `inline_summary`, `artifact_reference`, and `tool_only`; tool-only is marked omitted | Overall 60,000-char, JSON-section 36,000-char, and field 8,000-char truncation notices exist only inside the unstored full prompt |
| Prompt size | Full text can be counted after retrieval | No persisted char/byte/token count | Usage input tokens include conversation/provider/cache semantics and are not a packet-size measurement |
| Transcript/output | Final output on attempt plus ordered streamed output events | Ordered streamed output events only | Carrier formatting differs; no canonical end/completeness marker or retained raw stream contract |
| Tool activity | Structured action log where parser succeeds | Action log is returned but not persisted; some raw/formatted stream lines may contain tools | Graph tool sequence, arguments, results, and repeated-call evidence are not reliably queryable |
| Repository boundary | Attempt start/end commits for legacy handoff | File-state record and snapshot on every submitted graph agent execution | Graph record is a whole-worktree boundary, not a proven node-only delta; normal producer omits diffstat/content hashes |
| Output records | Attempt/checklist/commit evidence | Typed accepted records with provenance and graph positions | Generic candidate value is only `submitted by graph runner`; it does not describe changed content |

`hydrate_artifact_excerpt` verifies and bounds an explicitly supplied CAS
reference, but there is no production caller. Normal graph prompt assembly strips
check stdout/stderr CAS references and includes only their tails. An
`artifact_reference` hydration policy places metadata in the prompt; it does not
hydrate artifact content. These distinctions block any claim that an agent saw
the contents merely because an artifact record existed.

### Usage, cost, pricing, and rollups

When runner execution returns an `ExecutionResult`, usage extraction normalizes
provider input-token semantics so canonical input includes cache-read and
cache-creation tokens. It can produce one immutable `ModelTokenUsage` per
parent/sub-agent model with output, cache components, reasoning output, finish
reasons, measured execution latency, computed cost, and `rate_missing`. Latency
is copied to every per-model fact, but graph and cross-run reducers count it once
per `(run_id, execution_id)` using the first usage index; `num_actions` is placed
only on usage index zero. If the runner raises instead of returning, graph and
legacy phase handlers bypass extraction and storage, so provider-consumed tokens
can have no usage fact.

Pricing resolution applies these production rules:

- A complete, explicitly zero rate entry is `local_no_provider_cost`, has
  `rate_missing == false`, and legitimately computes zero.
- An unmatched model is `unpriced_provider`, while no model is
  `no_static_default`; both have `rate_missing == true` and zero only as the
  unavailable numeric cost, not as proof of no cost.
- For a matched entry, every absent rate field defaults to zero. Any positive
  input or output rate classifies the entry as `provider_billed` with
  `rate_missing == false`, even if cache or other rate fields were omitted.
  Positive-rate entry completeness is not validated.
- A matched entry with no positive input/output rate is
  `local_no_provider_cost` only when all four fields are explicitly present and
  zero. Otherwise it is `unpriced_provider`.

That distinction survives in `ModelTokenUsage.rate_missing`. It also survives in
graph cost rollups as `has_rate_missing`, missing-rate execution count, and
missing-rate input/output tokens. A rollup's `cost_usd` is only the sum of known
numeric costs and must be read together with those fields. An unpriced share can
be deterministically computed from the counts, but no share field or complete
derivation contract currently exists.

Important limitations prevent a broader price-coverage claim:

- `ModelCostResolution.cost_classification` and the resolved rate values are not
  persisted. Only computed cost and `rate_missing` remain, despite
  `model_costs.yaml` saying rates are embedded in usage records.
- A partially populated matched entry with positive input or output is treated as
  priced; omitted rate categories silently price at zero. `rate_missing == false`
  therefore proves a matched positive-rate classification, not a complete rate
  card.
- `model_costs.yaml` covers a small fixed model set. Custom/dynamic models are
  explicitly allowed by runner configuration and therefore can be unpriced.
- Exactly zero or entirely absent provider usage produces no usage fact. Missing
  telemetry and a genuinely zero-token execution are indistinguishable.
- A runner exception before `ExecutionResult` return also produces no usage fact
  in graph or legacy phase handling. Streamed output or failure evidence may show
  that work occurred without making consumed tokens or cost recoverable.
- Graph usage facts for sub-agents retain model and execution but not sub-agent
  ID/type, so attribution stops at node execution and model.
- `compute_run_metrics` treats a summed persisted cost of zero as though no
  captured cost exists and may fall back to approximate model pricing, including
  a `gpt-4o` default. That can turn both explicit local zero and unpriced usage
  into a nonzero run estimate. The per-model schema/UI remains honest through
  `rate_missing`, but the run-level `estimated_cost_usd` is not a safe
  unpriced-versus-zero source.
- `scripts/cost_report.py` aggregates legacy `cost_records.cost_usd` without
  reading nested `rate_missing`; unpriced legacy rows therefore contribute zero
  with no coverage caveat.
- The cross-run endpoint intentionally excludes legacy `CostRecordModel` rows.
  It supports graph-only comparisons and cannot represent fleet-wide coverage
  while legacy runs exist or exception-terminated executions are unmetered.

The graph rollup supports cross-run grouping by day, node kind, model, profile,
and run, plus status, runner, and time filters. It does not group/filter by
routine SHA, repository, node ID, task region, attempt, phase, outcome, patch,
intervention, or detector. It does not emit drill-through event IDs, expected
execution counts, missing-node lists, price-coverage ratio, budget pace, or a
comparable-cohort definition.

### Detector inputs and convergence

The repository contains enough raw facts for some future deterministic work, but
availability of inputs is not an implemented detector:

| Desired signal | Existing inputs | Current producer/derivation result |
|---|---|---|
| Repeated commands/tools | Legacy action-log tool names/arguments/results; graph runner output may contain carrier-specific tool lines; OpenHands process-local normalized command/tool window | Only OpenHands has a wired local detector. Its window, repeated command, and verdict are not persisted. No cross-run or graph detector |
| Repeated reasoning | OpenHands process-local first-200-character MD5 fingerprints | Wired only to local pause; hashes/verdict not persisted and not suitable as user evidence |
| No-output stall | CLI subprocess time since output and nudge count; graph heartbeat/lease/events/outbox facts | CLI nudger can kill a process; no shared stalled classifier or persisted threshold evaluation |
| Prompt pressure | Full legacy prompt text; graph input IDs/policies and unstored bounded prompt; usage input tokens | No canonical packet size, context-window denominator, pressure algorithm, threshold, or event |
| Retry information delta | Attempt/graph attempt numbers, verification grades/reasons, prompt summaries, candidates, file-state snapshots, output and usage | No packet/candidate/activity delta producer and no information-delta algorithm |
| Verifier/grade churn | Legacy grade events/snapshots; graph verification records with requirement grades and attempt/candidate IDs | No churn detector or cross-run aggregation |
| Evidence convergence | Requirement-version support freshness and verification/check/output records | Requirement support freshness is implemented, but no convergence rule, time window, confidence rule, or run-health output |
| Runaway | Usage facts, runner-local repetition inputs, action limits, planner-generation budget | No spend cap/pace, combined detector, current offender, or `runaway` event/classification |
| Degraded | Grade/retry/patch rejection facts and max-attempt fields | No shared classifier or threshold |
| Stalled | Event timestamps, heartbeats, active leases, outbox state | No persisted last-successful-event join, threshold, or classifier |
| Steered/directive binding | No typed steering directive capability | No binding record and therefore no safe delivery proof |

### Closed-scope demand disposition

The table covers all 44 `evidence-telemetry` items in `catalog/scope.yaml`.
`Current input` means a reachable producer emits the raw fact; it does not admit
the named derived claim.

| Scope key(s) | Audit disposition | Evidence or missing condition |
|---|---|---|
| `jobs.J1.health-class` | gap | No shared health classifier or health event/field |
| `jobs.J1.last-event-age`, `honesty.live-input-age` | derivable input only | Event timestamps/positions exist, but complete workflow+graph last-event join, clock, threshold, and age field do not |
| `jobs.J1.budget-pace` | gap | Usage exists only for executions returning metered results; no run spend/token cap, pace algorithm, time-window output, or exception-usage recovery |
| `jobs.J3.evidence` | current input | Decision, patch, command rejection, record, and citation events provide identities and reasons; causal scope remains record-specific |
| `jobs.J4.ordered-events` | current but split | Durable global position orders SQL rows; complete public chronology requires joining workflow and graph streams |
| `jobs.J4.requirement-grade-changes` | current input | Legacy grade events and graph verification records carry requirement, grade, reason, attempt/candidate context; no normalized cross-carrier history endpoint |
| `jobs.J5.bound-input-records` | partial current | Graph prompt summary has every input-port record ID and compact details; legacy prompts have text but no normalized bindings |
| `jobs.J5.omitted-referenced-context` | partial current | Graph hydration policy and missing/tool-only status exist; section/field/record-summary truncation is not durably complete |
| `jobs.J5.prompt-size`, `jobs.J7.prompt-size` | gap for graph, derivable for legacy | No persisted graph prompt size/hash; legacy full prompt can be counted but no producer publishes size |
| `jobs.J5.transcript` | partial current | Streamed output is durable and legacy action log is structured; graph has no canonical complete transcript/action log |
| `jobs.J5.tools` | partial current | Legacy structured tool events; graph persistence is carrier-specific output only |
| `jobs.J5.file-delta` | partial current | Graph boundary has paths/status and immutable snapshot IDs; no normal diffstat/content delta and node-only causation is unproven. Legacy commits are boundaries, not persisted diffs |
| `jobs.J5.usage`, `jobs.J8.tokens`, `jobs.J8.duration` | partial current with unknown coverage | Per-model token and measured execution duration facts are wired only after `ExecutionResult` return; absent/exact-zero telemetry and exception-terminated executions emit no usage fact even when provider work occurred |
| `jobs.J6.retry-information-delta`, `jobs.J7.retries-without-new-information` | gap | Inputs exist across attempts, prompts, records, grades, files, and usage; no defined or implemented comparison |
| `jobs.J6.budget` | gap | Planner generation and runner action limits are not an operator intervention cost budget |
| `jobs.J7.spend-tokens-by-node-kind` | partial current for graph | Cross-run endpoint directly groups persisted graph usage by node kind; legacy, exact-zero/no-reported, and exception-terminated executions without usage events are excluded |
| `jobs.J7.unpriced-share`, `jobs.J8.price-coverage` | partial/derivable with unknown denominator | Graph rollup exposes recorded numerator/denominator inputs and missing-rate counts, not a share/coverage field; missing and exception-terminated usage is outside the denominator; matched partially populated positive-rate entries appear priced; legacy report loses coverage |
| `honesty.unpriced-not-zero` | mixed | Per-model facts and graph rollup preserve `rate_missing`; run-level estimate fallback and legacy report can misrepresent unpriced usage |
| `jobs.J7.repeated-work` | gap as evidence product | OpenHands has process-local command/read/reasoning detection, but no durable verdict/input window or carrier-wide/cross-run detector |
| `jobs.J7.verifier-churn`, `jobs.J8.grade-churn` | gap | Grade history inputs exist; no churn definition, aggregation, or drill-through finding |
| `jobs.J7.prompt-pressure` | gap | No canonical prompt-size/context-limit inputs or detector |
| `journeys.A.no-runaway-signal`, `ia.health.runaway` | gap | Absence of a runaway event is not evidence of no runaway; classifier does not exist |
| `journeys.B.wait-age` | derivable input only | Requests/decisions/events have timestamps; no wait-start precedence or age projection |
| `journeys.C.cost-of-another-attempt` | gap | Historical returned-execution cost exists with unknown exception coverage; no cohort/phase estimator, uncertainty, or approximate result |
| `journeys.C.candidate-delta` | gap/partial inputs | Candidate IDs, generic candidate records, file snapshots, commits, prompts, and outputs exist; no canonical candidate content/delta |
| `journeys.C.causal-gap` | gap | Ordered prompt/grade/file/tool evidence does not establish causal mechanism; no causal-gap contract |
| `journeys.C.directive-binding`, `honesty.directive-binding-proof`, `ia.health.steered` | gap | Typed steering directive and durable packet binding are absent. Prompt summaries must not be repurposed as directive proof |
| `journeys.D.file-state-boundary` | current for graph | Callback producer captures, classifies, snapshots, accepts/rejects, and exposes graph file-state evidence |
| `journeys.E.missing-node-attribution` | gap | Usage facts identify reporting nodes, but there is no expected-execution denominator or list of nodes missing telemetry after absent, zero, or exception-terminated usage |
| `journeys.E.detector-evidence` | gap | Named cross-run detectors and durable detector findings do not exist |
| `journeys.continuity.derived-evidence-freshness` | partial current | Requirement support has explicit stale rules; other derived claims have no contracts or freshness outputs |
| `ia.health.evidence-convergence` | gap with one current input | Requirement support freshness is current; convergence algorithm/output is absent |
| `ia.health.degraded` | gap | No repeated-grade/attempt/patch-loop classifier |
| `ia.health.stalled` | gap | Heartbeat/event/outbox inputs exist; no thresholded shared result |

### Test evidence and gaps

High-value exercised paths found in tests:

- `tests/integration/test_event_store_wiring.py` exercises workflow event DB and
  JSONL dual output, positions, batching, and idempotent observer replay.
- `tests/integration/test_event_log_durability.py` exercises the SQL identity and
  projection/replay contract. It also explicitly proves the table has no event ID.
- `tests/integration/test_graph_event_store.py` exercises graph append/read,
  durable record base fields, summaries, and artifact-reference records.
- `tests/integration/test_graph_fr09_acceptance.py` exercises real graph dispatch
  context construction, runtime-start prompt summaries, node detail readback,
  input IDs, hydration policies, tools, lease, and base snapshot.
- `tests/unit/test_artifact_prompt_hydration.py` proves explicit CAS excerpt
  hydration and that default check prompt evidence retains tails but removes refs.
- `tests/integration/test_output_batching.py` proves fewer events than lines,
  monotonic gap-free line offsets, ordering, and flush behavior.
- `tests/integration/test_api_activity.py` proves full and default-summary output
  readback from `events_v2` and SSE resume identity.
- `tests/integration/test_graph_file_state_boundary.py` exercises production
  callback capture, snapshots, restore, residue, secret rejection, lease release,
  and clean retry.
- `tests/integration/test_graph_file_state_report_api.py` exercises report
  projection. Its fixture includes a `git.diff_summary`, but the normal producer
  in `_file_state_output_record` does not emit that field; the test does not prove
  producer wiring for diffstat.
- `tests/unit/test_graph_file_state.py` exercises deterministic classification,
  external manifests, secrets, escapes, and residue projection.
- `tests/unit/test_artifact_store.py` and
  `tests/integration/test_artifact_api.py` exercise CAS deduplication, permissions,
  integrity, range reads, run reference authorization, project-root resolution,
  publication/GC coordination, and missing/corrupt states.
- `tests/integration/test_graph_usage_persistence.py` exercises controller
  production commands, idempotent usage keys, run read-model updates, replay,
  legacy preservation, provenance hiding, and concurrent writes after usage facts
  are available. It does not establish usage capture when runner execution raises.
- `tests/unit/test_runner_usage_metadata.py` exercises provider metadata,
  parent/sub-agent facts, and measured graph/legacy execution latency.
- `tests/unit/test_model_costs.py` exercises unmatched/partial-zero versus
  explicit-zero classification, model-prefix matching, and matched positive
  input rates with omitted fields. It does not enforce complete positive rate
  cards because production does not validate completeness.
- `tests/unit/test_cost_rollup.py` exercises all dimensions, run-scoped execution
  identity, once-only latency/actions, missing-rate counts/tokens, and caps.
- `tests/integration/test_api_cost_rollup.py` exercises graph-only SQL filtering,
  cross-run grouping, literals, time ranges, and input bounds.
- `tests/integration/test_cost_records.py` exercises legacy prompt/output/action
  interaction rows, phase cost rows, usage, and the separate legacy report.
- `tests/unit/test_repetition_detector.py` exercises detector pure logic. It does
  not prove a durable detector event or graph/cross-run finding because none is
  produced.

No inspected test establishes usage persistence for exception-terminated graph
or legacy runner work, complete positive price cards, all-carrier transcript
completeness, graph action log persistence, exact graph prompt replay, prompt
size/pressure, candidate or retry information delta, missing-node coverage,
budget pace, comparable cohorts, cost-of-next-attempt, health classifications,
convergence, or durable detector drill-through. The report validator checks
handoff structure only; it does not validate these implementation claims.

## Important uncertainties

- Live providers may omit, rename, or redefine usage fields. Parser and fixture
  tests do not establish production coverage for every selectable runner/model.
- A graph execution that reports no usage is indistinguishable from telemetry
  loss or legitimate zero usage. This blocks complete price and node coverage.
- A graph or legacy runner that consumes provider tokens and then raises before
  returning `ExecutionResult` bypasses usage extraction. Failure events/output do
  not reconstruct those tokens, so spend remains unknown rather than zero.
- `rate_missing == false` does not prove rate-card completeness: a matched entry
  with positive input or output can omit other fields, which default to zero.
- Graph output events may retain enough runner-native data to reconstruct some
  tool activity for a particular carrier, but there is no canonical contract or
  completeness marker. Treat graph transcript/tool coverage as partial.
- File-state snapshots identify the observed worktree boundary. Concurrent or
  cumulative writes can make `producer_node_id` an observer attribution rather
  than exclusive causal authorship.
- Requirement support freshness is deterministic within one graph stream, but
  the planner prompt summary omits the actual freshness values. Exact packet
  replay at the start position has not been implemented as a public operation.
- Artifact references can mean a verified CAS blob, a generic path declaration,
  a worktree file captured by git, or a legacy DB interaction row. A consumer
  must inspect type and storage boundary rather than use `artifact` as one alias.
- The Phase 0 hash snapshot covers the JTBD/design sources but not the decisive
  implementation and test files in this audit. Their drift is not currently
  guarded by the foundation validator.

## Conflicts found

1. `docs/jtbd/jobs.md` says most raw J5 evidence is current. Producer wiring
   contradicts that as an all-run statement: full prompts/action logs are legacy
   only, while graph runs persist a compact packet summary and carrier-dependent
   output stream but discard the structured action log.
2. `model_costs.yaml` says rates are embedded into usage records. Current
   `ModelTokenUsage` persists computed `cost_usd` and `rate_missing`, not the
   resolved rate snapshot or `cost_classification`; matched positive entries also
   are not checked for complete rate fields.
3. The per-model and graph-rollup boundaries preserve unpriced status, but
   `compute_run_metrics` can replace zero/unpriced captured cost with an
   approximate nonzero estimate, and `scripts/cost_report.py` sums legacy zeros
   without coverage. The repository therefore has conflicting cost-honesty
   projections.
4. Generic graph `ArtifactReference` records look like durable artifact evidence
   but are path declarations without CAS publication, existence checking, or
   content integrity. Only typed check-output CAS references are downloadable by
   the artifact endpoint.
5. The activity endpoint is described as a run activity log but includes only a
   selected subset of graph events. It cannot serve as the complete ordered
   evidence ledger without the graph-event stream.
6. The file-state report accepts and renders a `diff_summary` fixture, while the
   production file-state boundary producer does not generate diff summary data.
7. Runner-local repetition and no-output controls are implemented, but the JTBD
   shared health model requires named, inspectable, cross-run detector evidence.
   Local process termination must not be normalized into that absent capability.
8. Source documentation describes usage as current, but usage extraction is
   post-return. Exception-terminated graph and legacy runner work can consume
   provider tokens while leaving no usage record.

## Decisions required

Normalization and Phase 2 should decide, without inventing capability:

1. Whether `current transcript/tool evidence` is explicitly carrier- and
   execution-mode-qualified, or the broader demand is classified as a gap.
2. Whether graph prompt summaries are admitted only as packet metadata, while
   exact prompt delivery, prompt size, truncation accounting, and directive
   binding remain gaps.
3. Whether graph-only cost rollup is a current scoped capability and fleet-wide
   rollup remains a gap until legacy, exception-terminated, and other
   missing-execution coverage are explicit.
4. Whether run-level estimated cost is excluded from honest price-coverage
   derivations because it can conflate explicit zero, unpriced, and approximate.
5. Whether file-state producer attribution is defined as `observed at node
   callback` rather than `caused by node`, unless stronger isolation evidence is
   available.
6. Whether implementation/test source files need a new content-hash snapshot
   before these findings can be normalized as non-stale evidence.
7. Whether `rate_missing == false` is accepted only as a matched-price signal,
   not proof that every billable category had an explicit rate.

No human product decision can make health, pressure, churn, convergence, retry
delta, causal gap, budget pace, next-attempt cost, directive binding, or missing
node attribution current without implementation evidence and a complete
derivation contract.

## Artifact paths

- `research/ui-foundation/agent-reports/05-evidence-telemetry.md`
- `.superpowers/sdd/task-7-audit-report.md`

No canonical catalog, reality model, capability registry, product source, test,
database, or git artifact was modified by this task.

## Evidence pointers

Primary implementation symbols:

- Workflow identity/wiring: `WorkflowEvent`, `SqliteEventStore.append`,
  `create_wired_event_store_v2`, `OutputBatcher._flush_entry`
- Graph identity/wiring: `EventEnvelope`, `GraphController.handle_command`,
  `GraphEventStore.append_events`, `graph_aggregate_id`
- Durable record base: `_add_durable_record_base_fields`,
  `_validate_durable_record_base_fields`
- Prompt production: `_prompt_for_node`, `_prompt_summary_for_node`,
  `_planner_evidence`, `_hydrated_bound_record`,
  `GraphDispatchExecutor._execution_context`,
  `GraphDispatchExecutor._acknowledge_start`
- Record/citation production: `_output_records_for_submit`,
  `_evaluated_record_citations`, `_add_evaluated_record_citations`,
  `GraphDispatchExecutor._submit_callback`
- File evidence: `collect_worktree_status`, `capture_file_state_boundary`,
  `_file_state_output_record`, `classify_file_state`
- Artifact evidence: `FilesystemArtifactStore.put/read`,
  `_externalize_check_output`, `_artifact_reference_for_run`,
  `hydrate_artifact_excerpt`
- Legacy trace/cost wiring: `PhaseHandler._execute_building`,
  `PhaseHandler._execute_verifying`, `PhaseHandler._execute_recovering`, the
  post-`_execute_agent` calls to `extract_metrics_and_usage`,
  `AttemptStore.store_attempt_prompt`, `AttemptStore.store_attempt_output`,
  `AttemptStore.store_attempt_metrics`, `_upsert_interaction_log_artifact`, and
  `_upsert_cost_record`
- Usage and pricing: `extract_metrics_and_usage`, `_usage_fact`,
  `load_cost_table` default-zero field loading, `_resolved_costs` positive
  input/output classification, `resolve_model_costs`,
  `calculate_model_usage_cost`, `GraphDispatchExecutor._run_agent` post-return
  extraction and exception branch, `GraphController.record_node_usage`,
  `_apply_record_node_usage`, and `GraphEventStore.apply_run_usage_events`
- Cross-run rollup: `load_cost_rollup_facts`, `compute_cost_rollup`,
  `get_cost_rollup`
- Freshness: `support_evidence_freshness_from_projection`,
  `requirement_freshness_facts_from_projection`,
  `project_planner_freshness_packet`
- Detector inputs: `RepetitionDetector`, `ReasoningRepetitionDetector`,
  `ActionBudget`, `Nudger`, and OpenHands `_StreamingVisualizer.on_event`
- Readbacks: `get_activity`, `get_graph_events`, `get_graph_node_detail`,
  `get_graph_file_state_report`, `get_run_artifact`, `get_run_trace`,
  `compute_run_metrics`

The source-document drift authority remains
`snapshot-2026-07-23-phase-0` in `catalog/evidence.yaml`. Line numbers are only
navigation aids; paths and symbols are the report's evidence pointers.

## Recommended next delegation

Delegate normalization to capability/derivation synthesis with these guards:

- Preserve the legacy/graph and carrier boundaries; do not merge them into one
  `transcript` or `prompt packet` capability.
- Admit raw event, record, graph file-state, CAS check artifact, graph usage, and
  graph cross-run rollup capabilities only with their stated identities,
  missing conditions, and freshness rules. Usage admission must be qualified to
  executions that returned a metered `ExecutionResult`; exception-consumed usage
  remains unknown.
- Keep unpriced usage separate from legitimate zero provider cost. Exclude
  run-level estimates and the legacy cost report from price-coverage evidence
  unless their honesty conflicts are resolved. Treat `rate_missing == false` as
  evidence of a matched classification, not a complete positive rate card.
- Require separate derivation contracts for last-event age, wait age, unpriced
  share, price coverage, candidate delta, retry information delta, prompt
  pressure, repeated work, verifier/grade churn, convergence, degraded, stalled,
  runaway, and cost of another attempt.
- Keep causal gap, intervention budget, missing-node attribution, and directive
  binding as gaps until their required evidence and producers exist.
- Ask an independent verifier to challenge exact prompt delivery, returned versus
  exception-terminated usage coverage, positive rate-card completeness, graph
  trace completeness, artifact-type distinctions, whole-worktree attribution,
  and all claims based only on test fixtures rather than production producers.
