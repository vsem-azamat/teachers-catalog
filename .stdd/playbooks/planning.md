---
name: stdd-planning
description: Turn an agreed behavior contract into an executable, verifiable sequence of work
when: The behavior contract is agreed (docs edit drafted or committed) and the change is large enough to need ordered steps — before the first implementation edit, to fix the execution mode and delivery boundary.
---

# Planning

A plan is a disposable working artifact: it guides one execution and is thrown
away. It is never committed as a file — its home is the PR description (for
the durable summary) and `.stdd/plan.md` (for the working copy: per checkout,
gitignored, read by `stdd status`, survives compaction).

Write the plan for an executor with zero context and questionable taste:
exact file paths, exact names, exact commands. The planning session's
memory does not survive delegation or compaction — whatever the plan does
not say, the executor does not know.

## Structure

A good plan has, in order:

1. **Intent** — one paragraph: the problem and the agreed direction.
2. **Docs delta** — which permanent docs change and how (added / modified /
   removed rules, named per target file). This is the spec surface of the
   plan; keep it exact so the docs edit is mechanical.
3. **Global constraints** — the agreement's project-wide requirements
   (version floors, naming and copy rules, platform limits), one line
   each, exact values verbatim. Every step implicitly includes this
   section; a delegated worker gets it copied into the brief.
4. **Steps** — each step small enough to verify independently, written as
   checkboxes (`- [ ]`) so `stdd status` can report progress and the next
   open item. Per step:
   - what changes (files, functions);
   - the failing test that gates it (or the visual check, for frontend
     visual work — see the design-first exception in the method);
   - the verification command;
   - for a step that may be delegated: its interfaces — **consumes**
     (exact signatures it uses from earlier steps) and **produces**
     (exact names and types later steps rely on). A worker sees only its
     own slice; this block is how a neighbor's names reach it.

   Tag a step whose gate is a failing test with `[red: <substring of the
   test command>]` — it then closes only when a matching genuine red is
   recorded via `stdd red`, not when the box is ticked.

   The last step of a multi-step plan is always the independent review
   (see "The closing review"). Write it into the plan at planning time —
   the plan must carry the trigger, not the session's memory.
   Tag it `[review:]`: like `[red:]`, the tag closes only through the
   ledger (an approved verdict recorded by `stdd review`), never by
   ticking the box.
5. **Out of scope** — what this change deliberately does not do.
6. **Risks** — what could invalidate the plan and how you would notice.

## Plan failures

These patterns void a step — rewrite it before presenting the plan:

- "TBD", "TODO", "fill in later", "details during implementation".
- "Add appropriate error handling" / "handle edge cases" — name the cases.
- "Write tests for the above" without naming the test and its assertion.
- "Similar to step N" — repeat the exact names; steps are read in
  isolation.
- A check that names no runnable command — the visual-check exception
  still names the command that brings the surface up.
- A reference to a type, function, or file that neither the repository
  nor any step defines.

## Self-review before presenting

Re-read the docs delta with fresh eyes and check the plan against it:

1. **Coverage** — every agreed rule maps to a step; list any gap.
2. **Plan-failure scan** — search the plan for the patterns above.
3. **Name consistency** — signatures and names used by later steps match
   where earlier steps define them.

Fix findings inline and present once — a plan that survives this check
gets approved in one round instead of three.

## Rules

- Order steps so the system stays green between them.
- Write verification per step, not one "run all tests" at the end.
- A step that cannot fail its check is not a step — merge it into another.
- When execution contradicts the plan, update the plan, do not force the
  plan onto reality. If the *intent* changed, stop and re-enter
  brainstorming.
- Keep the durable parts flowing to their homes as you go: rules → docs
  edit, rationale → PR description. The plan itself must stay deletable at
  any moment without information loss.
- Surface plan-invalidating discoveries as one batched question, not one
  interrupt per finding.
- Cut scope explicitly: `stdd defer <text>` appends the cut to the plan's
  `## Deferred` section. Deferred work is carried into the PR
  description's out-of-scope, never silently dropped.

## Executing

Close planning with an explicit execution choice — a closed question to
the user, your recommendation first. Template (recommend **inline** for
tightly coupled steps, **delegated** for independent ones; lead with
whichever you recommend):

> Plan ready (N steps). How should it run?
> 1. **Inline (recommended)** — this session implements the steps itself.
> 2. **Delegated** — independent steps go to workers via delegate-slice;
>    this session orchestrates and reviews.

The modes differ only in who types: the loop and its recording stay
identical. Delegation is a context optimization, never a requirement —
it preserves the orchestrating session's window for coordination instead
of burning it on implementation detail.

Record the answer as a `Mode: inline|delegated` line at the top of the
plan working copy — the plan carries the mode, not the session's memory,
so the choice survives compaction.

## The closing review

Every multi-step plan ends the same way, inline or delegated: an
independent review of the cumulative diff, before the evidence line and
the PR. Independence means a fresh context — the reviewer sees the
plan's intent, the docs delta, and the diff, never the implementing
session's history. A self-review by the session that wrote the code is
not independent: rationales in its own summary are the implementer
grading their own work. Two verdicts, in order: spec compliance against
the plan (missing / extra / misunderstood), then code quality on what
was built.
Use one of the route-specific commands below. Each invocation builds the brief
(plan + diff + governing docs + the method's quality rubric + output
contract), records the request, derives the verdict from the findings, and
closes the `[review:]` item on approval. After `changes-requested`, fix the
findings and repeat the same route-specific command; the newest verdict
controls the item.
`stdd review --via subagent` prints the brief path: hand it to a fresh
read-only subagent, then feed its JSON back through
`stdd review --result <file>`.

## The final report

When the plan is exhausted, report to the user —
in their language, for a human deciding what happens next, not as a
second copy of the ledger:

1. **Outcome first** — one or two sentences: what shipped and what
   proves it (tests and gate).
   Include the independent review verdict in that proof.
2. **Deviations from the plan** — deferred cuts, extra work, decisions
   changed mid-flight. If there are none, say so in one line.
3. **The technical trail last** — commands, file:line references,
   round counts, for the reader who wants them.

The machine record (findings JSON, ledger events, evidence line) already
exists; the report earns its place only by being readable — plain
sentences over verdict tables, terms spelled out over shorthand.
