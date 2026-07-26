---
name: stdd-start-change
description: Classify a request, open durable task state only for changes, and route to the smallest applicable workflow
when: A new implementation, fix, refactor, investigation, or repository change is beginning.
---

# Start change

Classify the request before writing task state:

- read-only question or diagnosis → invoke `stdd-investigation`; do not start a
  task or write the ledger;
- uncertain behavior or scope → invoke `stdd-brainstorming`;
- agreed multi-step behavior → invoke `stdd-planning`;
- known defect without a diagnosis → invoke `stdd-debugging`;
- small agreed change → invoke `stdd-implement` directly.

For every route that may change the repository, open one task boundary before
carrying state across prompts:

```bash
stdd task start "<short change name>"
stdd status --local
```

If another task is active, do not reset it silently. Finish it, continue it,
or ask the user which task owns the checkout.

For a change, read `.stdd/method.md` and the canonical docs governing the
touched behavior. The classification is a routing decision, not ceremony:
skip workflows that do not apply, but never skip a mechanical contract that
does.
