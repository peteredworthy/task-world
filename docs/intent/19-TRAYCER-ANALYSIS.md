# Deep Review: Traycer AI and Epic Mode

## Competitive Analysis for Orchestrator

---

## What Traycer Is

Traycer is a **spec-driven development orchestration layer** that sits between the human and their coding agents. It's a VS Code extension (Bay Area startup) that positions itself not as a replacement for Cursor/Claude Code/Windsurf, but as the *planning and verification layer* that makes those agents more effective. Their tagline: "Plan here, execute anywhere."

The core loop is: **Intent → Spec → Plan → Agent Handoff → Verification → Iteration**

This is extremely close to what we're building. They are the most direct competitor I've seen.

---

## Product Modes

Traycer has evolved into four distinct operational modes. Understanding these matters because Epic Mode is *additive* — it sits on top of Phases Mode, not instead of it.

### 1. Plan Mode (Original)
Single-task planning. Describe what you want, Traycer creates a detailed file-by-file plan, you hand it off to an agent. Think of this as "one-shot" — no phases, no decomposition.

### 2. Phases Mode (Core Workflow)
This is Traycer's primary execution mode and the closest analog to our Routines. A high-level objective gets decomposed into sequential **phases** — ordered chunks of work. Each phase gets:
- A detailed implementation plan (file-level, with classes/variables/call hierarchies)
- Agent handoff to the user's chosen coding agent
- Verification after execution
- Optional fix-forward loop if verification fails

Phases are checkpointed — you review each one before moving forward.

### 3. Review Mode
Code review without a plan. Traycer scans changes and generates comments by severity. Think PR review by AI.

### 4. Epic Mode (New)
The highest-level entry point. This is the "outer loop" that *produces the specs and tickets* that then get executed via Phases Mode. More on this below.

### 5. YOLO Mode (Automation Layer)
Not really a separate mode — it's a toggle on Phases Mode that automates the plan→handoff→verify→fix loop without human intervention. Configurable exit criteria (which severity levels trigger re-iteration).

---

## Deep Dive: Epic Mode

### The Problem It Solves

Epic Mode addresses what Traycer calls **intent drift** — the gap between what the human meant and what the agent builds. Their framing is sharp: "Agents aren't trying to be wrong, they're just filling in gaps." When critical context lives in your head or scattered across chat messages, agents invent what's missing.

This is *exactly* the problem our Routines solve. The shared diagnosis is: you need structured documentation of intent *before* agents start coding.

### How It Works

**Step 1: Choose a Workflow**
Epic Mode uses configurable "workflows" — sequences of commands that guide the conversation. Traycer ships a default "Agile Workflow" but users can create custom ones. Workflows define:
- An entrypoint command (the starting prompt)
- A sequence of command files (each with AI instructions)
- Branching paths (commands can specify valid next-steps)

This is analogous to our Routine YAML but more conversational and less structured. Their workflows guide a dialogue; our Routines define explicit steps with requirements.

**Step 2: Elicitation Dialogue**
This is Epic Mode's key differentiator from simple document generation. The AI doesn't just produce docs — it interviews the user. It asks pointed questions to surface:
- Constraints the user hasn't articulated
- Edge cases
- "Invisible rules" (implicit assumptions)
- Technical decisions that need to be made explicit

The output of this dialogue is a set of **artifacts**.

**Step 3: Artifact Generation**
Artifacts come in two types:

**Specs** (the "why" and "what"):
- PRDs — problem definition, who's affected, desired outcome
- Tech Docs — architecture, approach, implementation strategy
- Design Specs — user flows, UX decisions
- API Specs — contracts, endpoints, integration requirements

**Tickets** (the "do"):
- Actionable implementation units
- Track status: Todo → In Progress → Done
- Can be independently handed off to agents

Key insight: Epic Mode favors **mini-specs** — tightly scoped documents per aspect rather than one monolithic spec. Each is independently maintainable.

**Step 4: Full Context Awareness**
All specs and tickets within an epic share a single LLM context. When discussing one ticket, the AI has awareness of all related specs, decisions, and prior conversations. This is a significant architectural choice.

**Step 5: Selection and Handoff**
Once satisfied, the user selects specific specs + tickets and hands them off to:
- Phases Mode (for structured execution)
- Directly to a coding agent
- Referenced in further conversation

### Workflow Customization

Users can create custom workflows with:
- Custom command sequences
- Markdown instruction files per command
- Argument passing ($1, $2, etc.)
- Multi-path branching (AI suggests next step from allowed options)
- Cloneable defaults

---

## Verification System

Traycer's verification is LLM-based (not our checklist+grade approach). After each phase execution:

1. Traycer scans the codebase diff
2. Generates comments categorized by severity:
   - **Critical**: Blocks core functionality or plan requirements
   - **Major**: Significant issues affecting behavior/UX
   - **Minor**: Polish items, non-blocking
   - **Outdated**: No longer relevant due to changes
3. User can fix individually, batch-fix selected, or "fix all"
4. Two re-verification modes:
   - **Re-verify**: Focused check on previously flagged issues
   - **Fresh verification**: Complete new pass

In YOLO Mode, verification severity levels become automated exit criteria — if Critical/Major issues are found, the code is rejected and sent back to the agent automatically.

---

## Head-to-Head: Traycer vs Our Orchestrator

### Conceptual Alignment

| Concept | Traycer | Orchestrator |
|---------|---------|-------------|
| Core philosophy | Spec-driven development | Routine-driven development |
| Central problem | Intent drift | Intent drift + quality enforcement |
| Work decomposition | Epics → Tickets → Phases | Routines → Steps → Tasks |
| Planning format | Conversational + docs | Structured YAML |
| Verification model | LLM-generated severity comments | Checklist gates + grade thresholds |
| Agent relationship | Agent-agnostic orchestrator | Agent-agnostic orchestrator |
| Execution model | Phase-by-phase sequential | Step-by-step sequential |
| Automation | YOLO mode | Auto-verify + agent loop |

The overlap is substantial. Both products exist because the same problem is real.

### Where Traycer Is Ahead

**1. They're shipping and have users.**
Real testimonials, real pricing ($0/10/25/40/mo tiers), a VS Code extension that works today. One user claims they rebuilt their database, webhooks, APIs and switched payment processors in 6 days using Epic Mode.

**2. The elicitation dialogue is a good UX pattern.**
Epic Mode's "interview the human" approach is more accessible than writing a YAML routine from scratch. It lowers the barrier to structured planning. Users who can't or won't write specs get walked through creating them.

**3. Agent breadth.**
They integrate with Claude Code, Cursor, Windsurf, Cline, Augment Code, Codex CLI, and support custom CLI agents. They've already solved the "how do I launch and communicate with N different agents" problem.

**4. YOLO Mode is clever positioning.**
The fully autonomous plan→code→verify→fix loop is exactly what we'd build with auto-verify enabled. They got there first and named it well.

**5. Custom workflows.**
The ability for users/orgs to define custom workflow templates (sequences of commands with branching) is a lightweight version of our Routines but already working.

**6. Team collaboration (upcoming).**
They mention team features for distributing tickets — we haven't designed for multi-user yet.

### Where Orchestrator Is Stronger (By Design)

**1. Explicit requirements with checklist gates.**
Traycer's verification is an LLM looking at a diff and generating comments. It's smart but *fuzzy*. Our checklist approach is deterministic: CRITICAL requirement not marked DONE? Gate fails. Period. You can't accidentally ship past a missing requirement. Traycer's verification can miss things or generate contradictory comments across re-verifications (users report this in their community forums).

**2. Grade-based quality thresholds.**
Our A-F grading against a rubric is more structured than severity comments. A verifier explicitly grades each requirement against defined criteria. Traycer's "Critical/Major/Minor" is about *bugs found in code*, not *how well requirements were met*. These are fundamentally different verification models.

**3. Builder/Verifier separation.**
Our design uses distinct personas with fresh context — the verifier doesn't see the builder's process, only the output. Traycer's verification is a single LLM reviewing its own plan's execution. Our approach is closer to independent code review; theirs is closer to self-review.

**4. Structured, reproducible routines.**
A YAML routine is version-controlled, diffable, reusable, and machine-readable. Traycer's workflows are sequences of markdown command files in the UI — less portable, less composable. Our routines can be shared as files in a repo; theirs live in the tool.

**5. Explicit complexity management.**
Our "complexity budget" philosophy — workflows over agents, making complexity explicit — is a deeper architectural commitment. Traycer's complexity is largely hidden inside the LLM's planning. When it works, that's elegant. When it doesn't, it's opaque.

**6. No ref/use inheritance (intentional).**
We explicitly decided against template inheritance in routines, forcing each routine to be self-contained. This is a design decision for LLM comprehension. Traycer doesn't address this — their workflows don't have the same structural constraints.

**7. Git worktree isolation.**
Our design isolates each run in a git worktree. Traycer mentions worktrees in community feedback but it's not a first-class feature — users report it not persisting across iterations.

### Where We Differ Philosophically

**Traycer is conversational; we're declarative.**
Epic Mode's strength is the dialogue. The AI helps you *discover* what you need. Our Routines assume you know (or can learn) what you need and encode it explicitly. These serve different users at different stages.

**Traycer verifies output; we verify process.**
Their verification looks at the diff. Our checklist gates verify that the *builder followed the process* — did they address each requirement? Did the verifier grade each one? The output could still have bugs, but the process was followed. Traycer's approach could miss process gaps but catches output bugs. Ideally you want both.

**Traycer is SaaS-first; we're local-first.**
Traycer runs through their servers (artifact slots, usage-based pricing). Our design is fully local with SQLite persistence. Different trust models, different scalability constraints.

---

## Traycer's Weaknesses (From Community Feedback)

1. **Verification contradictions.** Users report re-verification generating contradictory comments (e.g., "move file from A to B" then next pass says "move file from B to A"). This is the core weakness of LLM-only verification.

2. **Artifact slot throttling.** The pricing model uses "artifact slots" that recharge on a timer. Users complain this slows development — you have to wait or pay $0.50 per instant refill. YOLO mode burns through slots quickly.

3. **Lint error noise.** Multiple sources mention Traycer generates excessive lint errors, requiring additional cleanup tools.

4. **Iteration timeouts.** Community reports of plan iterations timing out or getting stuck, especially on complex edits.

5. **VS Code only.** No terminal/CLI-only workflow. No web UI for monitoring. Everything lives in the IDE sidebar.

6. **No structured test requirements.** Verification is diff-analysis, not "did you write tests for this feature." There's no equivalent to our checklist approach for enforcing test coverage, documentation, or other non-code deliverables.

7. **YOLO needs computer awake.** The automation stops if the computer sleeps. This is a significant practical limitation for long-running tasks.

---

## Implications for Our Design

### Things to Steal or Adapt

**1. Elicitation as a first-class feature.**
Consider adding an "interview mode" before routine execution. Instead of requiring a pre-written routine, let the user describe intent and have the system generate a routine through dialogue. This could be an MCP tool or CLI command: `orchestrator plan "I want to add OAuth support"` → interactive elicitation → generates routine YAML.

**2. Verification severity categories.**
Our checklist has CRITICAL/EXPECTED/NICE. Traycer's verification comments have Critical/Major/Minor/Outdated. The "Outdated" category is smart — marking comments that are no longer relevant prevents the contradictory-verification problem. Consider adding a STALE/RESOLVED status for checklist items that are no longer applicable after revision.

**3. "Fix all" batch operations.**
Their ability to select verification comments and batch-send to the agent is a good UX pattern. Our design should support "address all failing requirements" as a single action rather than one-at-a-time.

**4. YOLO mode as a named concept.**
Our auto-verify is conceptually the same but less well-named. Consider surfacing this as an explicit "autonomous mode" toggle with clear configuration (which severity levels trigger re-iteration, max iterations, etc.).

**5. Custom workflow templates.**
Their workflow customization (sequences of commands with branching) validates our approach of user-defined routines. But we should consider making routine creation more accessible — not everyone wants to write YAML. A "create routine from conversation" path would combine the best of both approaches.

### Things to Explicitly Not Do

**1. Don't rely on LLM-only verification.**
The community reports of contradictory re-verification comments validate our checklist+grade approach. Structured verification catches what fuzzy verification misses.

**2. Don't use artifact slot throttling.**
Usage-based metering that pauses your workflow mid-execution is a terrible developer experience. Stay local-first with users providing their own LLM API keys.

**3. Don't require the IDE to stay open.**
Our server-based architecture (background process) is strictly better than requiring the VS Code window to remain active. Runs should survive IDE restarts.

**4. Don't hide complexity.**
Traycer's planning looks effortless but becomes opaque when it fails. Our explicit routines trade initial convenience for long-term debuggability. This is the right tradeoff for serious engineering work.

### Things That Validate Our Approach

1. **The problem is real.** Traycer's traction proves intent drift is a genuine pain point.
2. **Spec-driven development is catching on.** The DEV.to article mentions Traycer, Kiro, and Spec-kit as a category. We're entering an emerging space, not inventing one.
3. **Agent-agnostic is the right posture.** Traycer's success with multiple agents validates our decision not to build our own agent.
4. **Verification between phases is non-negotiable.** Every review of Traycer praises the verification step. Our design makes it even more rigorous.
5. **Sequential phases with checkpoints work.** Traycer's Phases Mode is basically our Steps. The pattern is proven.

---

## Competitive Positioning

If Traycer is **"the workflow layer between your ideas and your AI coding agent"**, then Orchestrator is **"the quality assurance system that makes AI engineering reliable."**

Traycer's strength is accessibility and breadth — it's easy to start, works with many agents, and the elicitation dialogue is welcoming. Its weakness is verification depth and reproducibility.

Our strength should be rigor and determinism — structured routines, checklist gates, grade thresholds, builder/verifier separation, git isolation. Our weakness will be initial approachability (writing YAML is harder than chatting).

The ideal positioning: Traycer is for teams doing "AI-accelerated development." Orchestrator is for teams doing "AI-reliable engineering." The difference is whether your priority is *speed* or *correctness*.

---

## Risk Assessment

**Risk: Traycer adds structured verification.**
If they ship checklist-style gates (they're getting community requests for configurable re-verification limits), the gap narrows. Mitigation: Our builder/verifier separation and grade thresholds are architecturally distinct — harder to bolt on.

**Risk: Traycer adds routine-style definitions.**
Their custom workflows are already moving in this direction. If they add YAML export/import, they'd match our reproducibility story. Mitigation: Our routines are deeper (per-requirement definitions, model overrides, retry configs) and version-controlled as project files.

**Risk: "Good enough" wins.**
If most teams don't need our level of rigor, Traycer's lighter approach captures the market. Mitigation: Target engineering orgs specifically (our audience), not the broader "vibe coding" market.

**Risk: They ship team features first.**
Multi-user ticket distribution is coming for them. We haven't designed for it. Mitigation: Not in our MVP scope, but keep the architecture multi-user-ready.

---

## Critical Limitation: Traycer is Cloud-Dependent (No Self-Hosted Option)

Traycer's architecture splits into two parts:
1. **Local**: The VS Code/Cursor/Windsurf extension and your chosen coding agent
2. **Cloud**: All planning, verification, and artifact generation runs on Traycer's servers

This is a fundamental architectural choice with significant implications:

### What Runs on Traycer's Cloud

- **Planning LLM calls** — When you describe a task and Traycer generates phases/plans, those LLM calls (Sonnet 4.5, o3, GPT-5, etc.) go through their infrastructure
- **Verification** — The LLM-based code review/verification runs on their servers
- **Epic Mode elicitation** — The interview dialogue and spec generation
- **Artifact storage** — Plans, specs, tickets are stored in their system

### What Runs Locally

- **Code execution** — The actual coding agent (Claude Code, Cursor, etc.) runs on your machine
- **File access** — Your codebase stays local; Traycer indexes it but doesn't upload it wholesale
- **The VS Code extension** — UI and orchestration logic

### The Artifact Slot System

Traycer meters usage through "artifact slots" — a rechargeable battery model:

| Plan | Slots | Recharge Rate | Price |
|------|-------|---------------|-------|
| Free | 1 | Slow | $0 |
| Lite | 3 | Standard | $10/mo |
| Pro | 9 | 30 min/slot | $25/mo |
| Pro+ | 15 | Faster | $40/mo |

Each artifact (phase, plan, verification, review) consumes 1 slot. When you're out of slots, you either wait for recharge or pay $0.50 per instant refill.

### What's Missing (Per Community Feedback)

- **No BYOK (Bring Your Own Keys)** — Users are actively requesting the ability to use their own API keys for the planning/verification LLM calls. Not available.
- **No self-hosted option** — Cannot run Traycer's planning layer on your own infrastructure
- **No API** — Cannot integrate Traycer programmatically into CI/CD or other tools
- **No offline mode** — Extension requires constant connection to their servers

### Why This Matters

**For compliance-conscious teams:**
- Your task descriptions, requirements, and code context flow through their servers
- Generated plans and specs are stored in their infrastructure
- No on-premise deployment option

**For cost predictability:**
- Slot throttling can pause your workflow mid-execution
- YOLO mode (automated loops) burns through slots quickly
- Heavy users report the recharge limits "slow down the development process"

**For vendor independence:**
- Your workflows depend on their service availability
- Artifacts live in their system (though they claim permanent retention)
- No export/portability story for your specs and plans

**Our Positioning:** Orchestrator is fully local-first. SQLite database on your machine, routines as YAML files in your repo, user-provided API keys for LLM calls. The only external dependency is the LLM API itself, and users choose which provider. This is a fundamental architectural difference that appeals to security-conscious teams and enterprises with compliance requirements.

---

## The `idea_to_plan` Workflow: Our Validation of Superiority

We have a real-world planning workflow (`idea_to_plan_detailed.md`) that demonstrates capabilities Traycer cannot match:

### Features Our Workflow Uses That Traycer Lacks

| Feature | Our Capability | Traycer Gap |
|---------|---------------|-------------|
| **Human-only gates** | Stage 2 requires explicit human approval; LLM cannot bypass | Verification is always LLM-based |
| **Backward transitions** | "If conflicts emerge, RETURN to Stage 2" with loop limits | Linear phase progression only |
| **Dry-run simulation** | Stage 6 simulates execution with limited context to surface gaps | No equivalent — straight to execution |
| **Multi-artifact context** | Task explicitly declares which prior artifacts it needs | Context is implicit/automatic |
| **Resolution tracking** | `design-questions.md` tracks which questions are resolved | No structured resolution tracking |
| **Recursive gating** | Stages 3, 4, 5 all can bounce back to Stage 2 | No conditional backward flow |

### What This Means

Traycer's Epic Mode can generate specs and tickets through conversation, but it can't express **workflows with explicit control flow**. Their approach is:
1. Chat to produce documents
2. Select documents
3. Hand off to Phases Mode (linear)
4. Verify output

Our approach is:
1. Define workflow as YAML (version-controlled, reproducible)
2. Execute with explicit gates (human or automated)
3. Backtrack when conditions trigger
4. Simulate before execution
5. Track artifact state for conditional logic

The `idea_to_plan` workflow is a proof point: it's a real workflow that cannot be implemented in Traycer today. This is our differentiator — we're not just a "planning layer," we're a **workflow engine** with the control flow primitives that serious engineering requires.

### Implementation Status

Phase 9 of our implementation slices adds:
- Human-only gate type (Slice 9.1)
- Backward transitions with loop detection (Slice 9.2)
- Artifact registry for cross-step context (Slice 9.3)
- Dry-run verification mode (Slice 9.4)
- Multi-artifact context injection (Slice 9.5)
- The complete `idea_to_plan` routine as a working example (Slice 9.6)
