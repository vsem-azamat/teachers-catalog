---
name: stdd-brainstorming
description: Shape a fuzzy idea into an agreed behavior contract before any plan or code
when: A non-trivial change is requested and the requirements, scope, or approach are not yet pinned down.
---

# Brainstorming

The goal is agreement on **what** and **why** before anyone invests in **how**.
The output is not a document — it is a shared understanding that becomes a
docs edit and a PR description.

## Process

1. **Understand the current state first.** Read the relevant docs and the code
   the change will touch. Questions asked from ignorance waste the other
   side's time; questions asked from knowledge sharpen the idea.
2. **Ask one question at a time.** Prefer questions that eliminate whole
   branches of the design space: who is it for, what triggers it, what must
   never happen, what is explicitly out of scope. When the answer space is
   enumerable, offer it as a closed choice with your recommendation first —
   a closed question costs the other side seconds, an open one minutes.
   Keep open questions for genuinely open design space.
3. **Challenge scope creep in both directions.** If the idea is bigger than
   the need, say so and propose the smaller version. If the stated need hides
   a larger real problem, surface it.
4. **Propose 2–3 approaches with a recommendation.** For each: one paragraph,
   the trade-off that actually matters, and what it costs later. Recommend
   one; do not present a menu without an opinion.
5. **Converge on the behavior contract.** State the agreed behavior as rules
   precise enough to test. Confirm them explicitly.

## Output

- The agreed rules become the **docs edit** (the spec) — the first commit of
  the branch.
- The rationale, rejected alternatives, and scope decisions go into the
  **PR description** when the branch opens.
- Nothing from this conversation is committed as a standalone file.

## Anti-patterns

- Jumping to implementation detail while behavior is still unsettled.
- Asking multiple stacked questions at once.
- Writing a "spec document" instead of editing the real docs.
- Agreeing silently: if you disagree with the direction, say so with reasons.
