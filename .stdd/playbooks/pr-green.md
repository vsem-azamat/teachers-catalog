---
name: stdd-pr-green
description: A PR is done only when its required checks settle terminal-green on the current head
when: A PR/MR exists, or is about to be opened, for the current branch.
---

# PR Green

The discipline: local verification governs the inner loop; the PR's required
checks govern the definition of done. "CI started" and "pushed" are never
done.

## The one command

Do not hand-roll pollers, sleeps, or `gh pr checks` loops:

```bash
stdd ci --watch        # current branch's PR; stdd ci <n> --watch for another
```

It resolves the PR, pins the watch to the PR's **current head**, refuses to
settle until the check set is stable and fully terminal, restarts itself
when the head moves (amend, force-push, new commit), and exits 0 only on
terminal green — nonzero the moment a check fails terminally. On GitLab,
`glab ci status --live` is the nearest equivalent; the recognition table
below still applies.

## Recognition table

| You see | It means | Do |
| --- | --- | --- |
| Green summary seconds after a push, suspiciously few checks | The full check set has not registered yet | Trust only `stdd ci --watch` — it never settles on the first sighting of a set |
| A failure attached to an older SHA | Stale result, not a red | Nothing — the watch is pinned to the current head |
| `cancelled` on a superseded run | A concurrency twin, not a failure | Nothing to debug — `stdd ci` collapses same-named entries to the freshest run; re-run only if a ruleset still waits on that check |
| A required check failed on the current head | A real red — it outranks everything else | Pull the failed job's log (the error, not the job name), reproduce locally with the narrowest matching command, fix the root cause, push, re-watch |
| Checks green, but the change needs a deploy or migration to be observable | Green CI ≠ working | Verify the runtime surface the change touches before reporting done |
| The watch times out with checks still pending | Runner starvation or a hung job | Read the run page; re-run or escalate — never report green |

## After a real red

A fix-commit without a re-watch repeats the original mistake: every push
starts a new settlement, and only `stdd ci --watch` reaching terminal
green closes it.

## Before opening

Run the local lanes that cover the surfaces the diff touches — not only the
narrowest lane that proved the last edit. CI settlement stays the
authoritative backstop; pre-running the entire CI matrix locally is not the
goal.
