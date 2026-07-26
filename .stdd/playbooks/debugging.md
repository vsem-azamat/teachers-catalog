---
name: stdd-debugging
description: Find and fix the root cause of a defect, not its symptom
when: A bug, crash, failing test, or unexplained behavior is reported.
---

# Debugging

The discipline: no edit before a reproduction, no fix before a diagnosis.

## Process

1. **Reproduce first.** Turn the report into a deterministic reproduction —
   ideally a failing test. If you cannot reproduce it, you are not debugging
   yet; you are gathering facts.
2. **Read the actual error.** The full message, the stack, the logs around
   it. Do not pattern-match a familiar-looking symptom to a known failure —
   verify the evidence supports *this* cause.
3. **Form one hypothesis and test it cheaply.** Predict what you will observe
   if the hypothesis is true, then look. One hypothesis at a time; a change
   made under two hypotheses proves neither.
4. **Fix the root cause minimally.** The smallest change that removes the
   cause. Resist drive-by cleanup — it obscures the fix in review.
5. **Keep the reproduction as a regression test.** Red before the fix, green
   after, committed with it.
6. **Verify the fix in the original context**, not only in the reduced
   reproduction.

## Stop rules

- Two failed fix attempts mean the diagnosis is wrong. Stop editing, go back
  to step 2, and widen what you consider suspect — including your own
  earlier changes and the test itself.
- If the evidence contradicts the reported story, surface the contradiction
  instead of forcing a fix that matches the story.
- A fix you cannot explain is not a fix. Do not ship it.
