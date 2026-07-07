# External Evidence: Context Engineering for Long-Running Multi-Phase Agents

> Research digest compiled 2026-07-07. Confidence: **High** = primary source
> with data; **Med** = primary, qualitative; **Low** = secondary/inferred.
> Full link list in [../sources.md](../sources.md).

## 1. Context is a depleting resource; just-in-time beats pre-loading

- **Context rot** (Chroma, Jul 2025; High): accuracy degrades non-uniformly
  with input length even on trivial tasks, far below window limits;
  distractors amplify it. *Prompt assembly should have an explicit token
  budget; every section spends from it.*
- **Smallest set of high-signal tokens** (Anthropic, [Effective context
  engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents), Sep 2025; High-qualitative): prefer lightweight identifiers +
  runtime retrieval over pre-loaded dumps (Claude Code greps instead of
  indexing). *File-state sections should be pointers + short digests (paths,
  SHAs, one-line diffstats), not content — directly attacks our payload-bloat
  incident class.*
- **Four failure modes** (Breunig, Jun 2025; Med, echoed by Chroma data):
  poisoning (a wrong claim enters context and is re-referenced), distraction,
  confusion, clash. *Prior-attempt feedback is our poisoning vector: a wrong
  verifier diagnosis persisted in graph state gets re-injected every attempt.
  Feedback must be attributable and supersedable, not accreted.*

## 2. Prompt-caching economics constrain assembly

- Cache reads 0.1× base input; writes 1.25× (5-min TTL) or 2× (1-hour).
  (Claude docs; High.)
- **KV-cache hit rate is the production metric** (Manus, Jul 2025; High —
  production data): ~100:1 input:output ratios; 10× cost difference cached vs
  not; one-token prefix difference invalidates everything after it. Rules:
  stable prompt prefix (no timestamps), deterministic serialization,
  append-only context, never remove/reorder tools mid-run.
- *For us: order assembled prompts most-stable → most-volatile (static
  role/spec preamble → step context → per-attempt feedback); deterministic
  serialization of DB-derived sections (sorted keys). Fresh context per phase
  means every phase is a cold cache — a byte-stable shared preamble per agent
  role is the lever that makes fresh contexts affordable.*

## 3. Structured external memory

- **Letta/MemGPT memory blocks** (2025; Med): labeled, size-limited,
  DB-persisted blocks; context compiled from DB per request.
- **Mem0** (arXiv 2504.19413; High for benchmark, Med for transfer): extracted
  memory beats full-context replay on cost/latency and can beat on accuracy.
- *Our typed graph state already **is** the memory-block layer — prompts are
  compiled from DB state, which this literature says is the right pattern.
  Transferable specifics: (a) per-section size limits enforced at the schema
  level (would have capped the 28.8GB journal), (b) explicit block labels,
  (c) supersession semantics — blocks are replaced, not appended.*

## 4. Compaction and summarization — when, and what goes wrong

- **Clearing raw tool results is the safe first move** (Anthropic context
  management, Sep 2025; High): auto-clearing stale tool results alone +29% on
  agentic search; + file-based memory +39%; 84% token cut on a 100-turn eval.
- **Governance decay** (arXiv 2606.22528, Jun 2026; High): aggressive
  compaction raised constraint-violation rates from ~5-10% to 40-70%;
  **pinning constraints (exempting from compression) restored baseline**.
- **Prose summaries are unpredictably lossy** (arXiv 2605.08580, 2606.11213;
  Med): summarizer salience ≠ downstream need; trajectory-grounded validation
  of compaction (+8.8pp SWE-bench Verified).
- **Recency-truncation + light summary beats full history** (arXiv
  2606.10209, Jun 2026; High, single domain): full history 71% success/1.48M
  tokens; last-5-pairs 79%/535K; last-5 + rolling summary 91.6%/553K. Pruning
  eliminated stale-state-reference errors (47%→11% of failures).
- **Keep errors in context within an attempt** (Manus; Med): erasing failure
  traces removes the evidence the model uses to avoid repeating mistakes.

*Decision rule for us: **truncate/clear** raw tool output (recoverable),
**summarize** trajectory narrative only, **never summarize** constraints and
acceptance criteria — pin them, re-inject verbatim every attempt. Because our
state is event-sourced, prefer **re-derivation by reducers** over
summarization wherever possible: re-derived context can't poison; summaries
can. Between attempts, pass a structured failure record (what failed, where,
verbatim error), not prose narrative.*

## 5. Sub-agent isolation and the handoff contract

- Fresh-context workers fail primarily from **underspecified briefs**, not
  isolation (Anthropic multi-agent post, Jun 2025; High): each brief needs
  objective, output format, tool guidance, boundaries.
- Counter-position: "actions carry implicit decisions" (Cognition, Jun 2025;
  Med) — *doesn't apply to our sequential builder→verifier split, but does
  apply to builder→next-builder: attempt N's implicit decisions must be made
  explicit or attempt N+1 re-litigates them → a small "decisions register"
  (chosen approach, rejected alternatives + why) in durable state.*
- **Files/artifacts as the handoff interface** (Manus; Anthropic Sep 2025;
  Med/High): keep the URL, drop the content — compression stays *reversible*;
  todo.md **recitation** (rewriting the objective into the tail of context)
  fights lost-in-the-middle across ~50-call loops; Claude Code re-reads
  CLAUDE.md from disk after every compact — filesystem, not summary, is the
  source of truth for invariants.
- *Recite the task objective and acceptance criteria near the **end** of the
  assembled prompt, not only the top.*

## 6. Long-horizon scale facts

- SWE-bench-style sessions span millions of tokens, 100+ turns (Confucius
  Code Agent reports ~8M tokens, 154 turns avg; Med). Compaction policy, not
  window size, is the binding constraint.
- *Our per-phase attempts are a designed-in compaction boundary — each attempt
  boundary is a "compact to typed state" event. The literature says that's
  the strongest position, provided typed state captures decisions and
  constraints, not just outcomes.*

## Five most decision-relevant takeaways

1. **Pin constraints/acceptance criteria; never summarize them** (strongest
   quantitative result: 5-10% → 40-70% violations under compaction; pinning
   restores baseline). Verbatim re-injection every attempt + recitation near
   prompt end.
2. **Re-derive > summarize > truncate-blindly** — event-sourced state makes us
   uniquely positioned for re-derivation.
3. **Payload bloat is a schema problem**: per-field size limits + reversible
   pointer-based compression would have prevented the 28.8GB journal.
4. **Design prompt assembly around the cache**, stable→volatile, deterministic
   serialization.
5. **Attempt handoff needs three typed things**: the brief
   (objective/boundaries/output schema), a decisions register, a structured
   failure record. Everything else: discard or leave as filesystem artifacts
   fetched just-in-time.
