# User Story Documentation Process

This guide describes how we write and maintain the user story documentation for Orchestrator.

## What This Is (and Isn't)

This is a set of **narrative user stories** that describe the system from the outside in. Each story follows a named character through a real scenario, touching real API calls, real state transitions, and real system behavior. Together, the stories form a complete map of what the system does and why.

These stories are **not**:

- API reference docs (we have those separately)
- Implementation guides (see the slice documents)
- Test cases (though they should be verifiable against the running system)
- Marketing material (though they should be pleasant to read)

They sit in a gap between "how does this endpoint work?" and "why does any of this exist?" -- a gap that traditional documentation rarely fills.

## The Structure

### Backbone

The backbone is a single document (`BACKBONE.md`) that maps every major capability of the system to a position in the user's journey. Think of it as the table of contents for a novel. It answers: "what can this system do, and in what order does a user encounter those capabilities?"

The backbone uses a timeline structure:

```
Setup → Create → Configure → Execute → Monitor → Intervene → Complete → Review
```

Every feature in the system should appear somewhere on this timeline. If a feature doesn't fit, either the backbone is incomplete or the feature is.

### Stories

Each story (`story-*.md`) is a short narrative (aim for 3-5 minutes reading time) that follows a character through a specific scenario. Stories are numbered for ordering but the number doesn't imply importance.

A story should:

1. **Name the character and their situation** -- one sentence of context
2. **Walk through the journey step by step** -- what they do, what the system does
3. **Show the system responses** -- actual API shapes, status transitions, event payloads
4. **Include at least one thing going sideways** -- errors, retries, human intervention
5. **End with a resolution** -- the character's goal is achieved (or meaningfully not)

### Coverage Map

At the bottom of the backbone, maintain a **coverage map**: a checklist of every major system capability and which story exercises it. When a capability has no story, that's a gap to fill.

## Writing Guidelines

### Voice and Tone

Write in **present tense, third person**. The character does things; the system responds. Keep it conversational but precise -- you're explaining to a colleague over coffee, not writing a formal spec.

```
Good: "Maya hits create. The API validates her routine reference, discovers
       it's pinned to commit abc123, and spins up a draft run."

Bad:  "The user shall submit a POST request to the /api/runs endpoint
       with a valid routine_id parameter."

Also bad: "So basically what happens is the system like creates a run
           and stuff."
```

Humor should be **situational, not performative**. Don't add jokes -- let the absurdity of real scenarios do the work. An agent that gets stuck in a loop and needs nudging is inherently funny. You don't need to add a punchline.

### Technical Precision

Stories are narrative but they must be **mechanically accurate**. When you mention a state transition, use the real enum values. When you describe an API call, use the real endpoint shape. When you say "the gate checks all critical items," that should reflect what `gates.py` actually does.

```
Good: "The task moves to BUILDING. The agent gets a fresh prompt --
       no memory of its previous attempt, just the requirements and
       the feedback from the verifier."

Bad:  "The task starts building again with some context about what
       went wrong."
```

### Brevity

Each story should be **readable in one sitting** (3-5 minutes, roughly 800-1500 words). If a story is getting long, split it. The backbone exists so readers can find the story they need -- individual stories don't need to be comprehensive.

Omit what the reader can infer. Don't explain what an API is. Don't explain what git does. Trust the reader to be a developer.

### Characters

Use a small recurring cast (3-4 characters). This makes the stories feel connected and lets you build on previous context without re-explaining.

| Character | Role | Personality |
|-----------|------|-------------|
| **Maya** | Tech lead, primary user | Pragmatic, slightly impatient. Uses the web UI. |
| **Jordan** | Platform engineer | Builds integrations. Uses the API and CLI. |
| **The Agent** | The LLM agent (any backend) | Earnest, occasionally confused. Not a person but has presence. |

Don't over-characterize. A single adjective or reaction per story is enough. The characters exist to make "the user" concrete, not to carry a plot.

## Process for Writing New Stories

### 1. Check the Backbone

Before writing a story, check `BACKBONE.md` to see what's already covered. Find the gap you're filling. If the backbone doesn't have a slot for your capability, add one first.

### 2. Trace the Journey

Walk through the actual code path. Read the relevant router, service method, and engine logic. Note the exact state transitions, error cases, and event emissions. Your story needs to reflect reality.

### 3. Draft the Narrative

Write the story in one pass, following the character from trigger to resolution. Don't worry about getting every detail right -- get the shape right first.

### 4. Verify Against Code

Go back through the story and check every technical claim. Does that endpoint really return that shape? Does the state really transition that way? Fix any drift.

### 5. Add to Coverage Map

Update the backbone's coverage map. Mark which capabilities your story exercises.

### 6. Review for Length

If it's over ~1500 words, find the natural split point. Two focused stories are better than one sprawling one.

## Maintaining Stories

Stories should be updated when the system changes in ways that invalidate them. This is a judgment call -- not every refactor needs a story update. But if a state transition changes, an endpoint moves, or a concept is renamed, the stories should follow.

The coverage map is the primary maintenance tool. When adding a new feature, check the map. If the feature isn't covered, decide whether it fits in an existing story or needs a new one.

## File Organization

```
docs/stories/
  PROCESS.md          -- this file
  BACKBONE.md         -- the journey map and coverage tracker
  story-01-*.md       -- individual stories, numbered for ordering
  story-02-*.md
  ...
```

Stories are numbered `01`, `02`, etc. The number determines reading order, not importance. New stories get the next available number. Don't renumber existing stories.
