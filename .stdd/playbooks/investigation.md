---
name: stdd-investigation
description: Read-only diagnosis — evidence-backed findings, no changes
when: Asked to diagnose, triage, or explain behavior WITHOUT changing anything.
---

# Investigation

The discipline: the deliverable is an evidence-backed diagnosis and an
explicit list of blockers — never an edit. For the fix that may follow,
switch to the debugging playbook; this one deliberately does not restate
it.

## Contract

- No file edits, no state-changing side effects — reads only.
- Every claim in the report is backed by evidence you actually observed,
  or labeled as unverified with the blocker named.

## Process

1. **Inventory the evidence channels first.** Before forming any theory,
   check what you can actually observe: forge CLI auth, container / DB /
   log access, environment-key **presence** (never values). Report dead
   channels as blockers immediately — do not silently work around a
   channel you could not reach.
2. **A hypothesis is not a diagnosis.** Test it against runtime signals —
   logs, states, reproductions — before reporting it as a finding. What
   you could not test, report as an explicitly unverified hypothesis with
   the blocker that prevented the test.
3. **Deliver the report**: the diagnosis (or ranked hypotheses) with its
   evidence, the blockers, and the narrowest next step a fixing session
   should take.
