---
name: stdd-finish-change
description: Close an implemented change with independent review, PR evidence, terminal CI, and runtime verification when required
when: Implementation is locally verified and the change is ready for review, delivery, or handoff.
---

# Finish change

Close the current checkout in this order:

1. Run the complete affected local verification.
2. Finish every plan item and run the independent closing review when the
   capability profile supports it.
3. Generate the PR evidence with `stdd evidence`; never hand-author a claim
   contradicted by the diff.
4. Open or update the PR/MR and wait for terminal checks. On GitHub use
   `stdd ci --watch`; on another forge use its adapter's equivalent.
5. If the change includes a deploy, migration, package publish, or other
   runtime effect, verify that surface separately. Green CI is not runtime
   proof.
6. Run `stdd task finish` only after the requested delivery boundary is
   actually complete.

Do not merge, deploy, publish, or mutate an external system unless the user
has authorized that action.

