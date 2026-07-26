# The STDD Method

This is the working contract. It is written for the agent or developer doing
the change, in the order the work happens.

## Sources of truth

Every repository adopting STDD names a **permanent docs tree** (for example
`docs/`) with an explicit hierarchy — typically product intent above domain
rules above implementation layers. When layers disagree, stop and reconcile
before implementing.

Three artifacts make claims about behavior, each in its own way:

- **Docs are the intended contract** — what the system is supposed to do.
- **Tests are the executable contract** — what the system provably does.
- **Code is the observed implementation** — what the system actually does.

A disagreement between them blocks implementation until they are reconciled.
None silently overrides the others: stale docs get corrected, wrong tests get
fixed, accidental behavior gets documented or removed — each resolution is an
explicit decision, not a default in favor of any one artifact.

## The loop

```
classify → read docs → docs edit (the spec) → failing test → implement → verify → PR evidence
```

1. **Classify the change.**
   - *Behavior:* anything a user, operator, or downstream system can observe —
     workflows, pricing, states, permissions, API contracts, copy with
     business meaning.
   - *Implementation-only:* refactors, lint fixes, build plumbing, mechanical
     dependency updates that alter no behavior or architecture contract.
2. **Read the relevant docs first.** For behavior changes, read the matching
   source-of-truth documents before proposing anything.
3. **Edit the docs — that edit is the spec.** Once the intended behavior is
   agreed, update missing, stale, or ambiguous docs before tests and
   production code. Make the docs edit the first reviewable unit — the first
   commit where commits are used, otherwise the opening docs-only diff of the
   PR — so the behavior contract can be reviewed on its own. A throwaway
   exploratory spike may precede this commitment; discard it or explicitly
   reclassify the change before review. If the docs already cover the
   behavior, do not add duplicate prose — record that they were checked (see
   PR evidence). Not every implementation detail deserves canonical prose.
4. **Write the failing test.** Red before green. Exception below.
5. **Implement** until the test passes, then refactor.
6. **Verify with the narrowest meaningful command.** Never claim "done",
   "fixed", or "clean" without fresh verification evidence. Narrowest
   meaningful governs the inner loop; once a PR exists, verification is
   complete only when its required checks settle terminal-green on the
   current head commit. `stdd ci --watch` is that wait, done right: it
   pins the watch to the PR's current head, refuses to settle until the
   check set is stable and fully terminal (a watcher attached right after
   a push sees a partial set — the classic early-settle trap), restarts
   itself when the head moves, and exits nonzero on a terminal failure.
   Duplicate rollup entries for the same check name (re-runs, cancelled
   concurrency twins) collapse to the freshest run, so a superseded
   cancel never reads as a red. Never hand-roll the poller.
7. **State PR evidence.** Every PR carries exactly one of:
   - `Docs updated first:` — list the changed docs;
   - `Docs checked, no change needed:` — list the docs and the reason;
   - `Docs not applicable:` — why the change is implementation-only.

   The line must name its evidence — docs paths or a reason. A bare label
   with nothing after the colon fails `stdd check-pr`, and only a line
   starting at the beginning of a line counts (quoted templates and code
   blocks do not).

   When no valid line exists but a near-miss does — a markdown-formatted
   label, a list or quote marker in front of it, or a wrong sentinel
   wording — `stdd check-pr` points at that line and prints the corrected
   form. The suggestion is advisory: the pass condition does not change.

   With `--base <ref>` the claim is verified against the actual diff:
   every doc path named after `Docs updated first:` must be a file changed
   between the base ref and `HEAD` (and at least one path must be named);
   paths named after `Docs checked, no change needed:` must exist in the
   tree. Claiming a docs update the diff does not contain fails CI.

   With `--pr <number|.>` the live PR is validated exactly as CI will see
   it: the body is fetched from the forge, the base is the PR's own, and
   the diff is taken against the PR's head commit — when the local checkout
   is not on that commit, the head is fetched rather than silently diffing
   the wrong tree. `.` resolves the current branch's PR.

   `stdd evidence --base <ref>` drafts the line from ground truth instead
   of recall. When canonical docs changed against the base, it prints the
   finished `Docs updated first:` line to stdout — safe to embed in a PR
   body via command substitution. When none changed, the remaining two
   sentinels need an authored reason: the templates go to stderr and the
   command exits nonzero, so substitution cannot silently embed a template.
   The base comes from `--base` or the `baseRef` key in `.stdd/config.json`;
   there is no built-in default.

## The frontend exception: design-first

Frontend **visual** work — layout, styling, markup structure, presentation
copy, component composition — is design-first, not test-first. A
failing-test-first loop forces the visual outcome to be specified before it
is explored; brittle rendering assertions then punish every design iteration.

The exception covers presentation, not meaning. Copy with business meaning —
prices, statuses, permissions, legal text, anything a user relies on as a
fact — is **behavior**: it goes through the docs edit and the normal loop.
Only its visual arrangement is design-first.

- Build the visual part freely; verify it visually (screenshots reviewed by a
  human).
- Never write tests asserting static copy, class names, or pure rendering
  output.
- After the visual part settles, add tests only for real behavior contracts:
  hooks, formatters, state transitions, eligibility and conditional logic,
  accessibility roles.
- Client-side **logic** follows the normal loop.

## Working artifacts are non-canonical by default

Plans, spec files, todo lists, handoff notes, and execution logs are working
artifacts. They help execution but can go stale as soon as the task or
checkout moves. When committed without an authority marker, they can outrank
fresher docs in code search and become a second source of truth.

The default STDD policy therefore keeps them uncommitted. This is a strong
default, not a universal ban: a team that needs an auditable design trail may
retain selected records when each record declares
`authority: non-canonical`, canonical retrieval rules exclude it by default,
and current behavior still has exactly one home in the permanent docs tree.
Narrow `forbiddenArtifacts` deliberately and enforce the authority marker
with `contentRules`; never weaken the boundary accidentally.

Where their content belongs instead:

| Content | Home |
| --- | --- |
| Durable rules (behavior, architecture, conventions) | The permanent docs tree, same PR |
| Design rationale, scope decisions, rejected alternatives | The PR description |
| Designs for deferred (not yet implemented) work | Dated entries in the project log (e.g. `docs/project/`) |
| Task lists, sequencing | The durable plan (`.stdd/plan.md`, per checkout — see below), PR body |

The project log is **not canonical**: its entries are dated records of
decisions and future intentions, never a description of the present. Cite
canonical docs for how the system behaves; cite the project log only for why
something is deferred or was decided.

Because a plain `grep` cannot tell authority levels apart, the boundary is
made machine-readable on both sides. Every project-log entry starts with
frontmatter declaring itself non-canonical:

```yaml
---
authority: non-canonical
status: deferred
---
```

And the agent instructions `stdd init` generates carry a retrieval rule: do
not search the project log unless the user explicitly asks for historical
rationale or deferred work.

`stdd check` enforces the configured artifact policy in CI; `stdd check-pr`
enforces the PR evidence line; `stdd doctor` reports a repository's overall adoption
health (setup, canonical docs, misleading artifacts, generated-file drift).
Manifest hashes prove that generated bytes have not changed since init; for
the installed method, `check` and `doctor` also compare those bytes with the
canonical method shipped by the running CLI, so a stale method and a matching
stale manifest cannot authenticate each other. Generated-looking method,
snippet, and native-skill files without a manifest are a partial install and
also fail the check, even when an exact generated path is occupied by a
directory, symlink, or other unsafe object. A malformed manifest — including a wrong generator or
version shape, a non-object document, an invalid generated path or exact
`sha256:<64 lowercase hex>` file hash, or malformed present target metadata —
is an actionable adoption finding in both `check` and `doctor`, never an
uncaught runtime error. Legacy manifests may omit target metadata; when
present, it must contain the complete known target schema. Every listed
output is inspected as a readable regular file without following symlinks;
directories, non-regular files, unreadable paths, and paths replaced during
inspection are stale findings rather than runtime errors. Profile cleanup
uses the same inspection boundary and never deletes an output it cannot
safely identify. Retirement is confined to a safely held parent-directory
identity: the verified inode is moved out of its agent or CI load path to an
unpredictable quarantine name and remains hash-accounted in the manifest;
re-init keeps that quarantine stable instead of attempting an unsafe
pathname deletion. When the runtime cannot provide the held-parent boundary,
cleanup preserves the old output instead. Cleanup completes before the
replacement manifest is published: a cleanup failure leaves the previous
manifest authoritative, while a hand-edited formerly generated file is
preserved but remains listed and reported stale until its owner removes or
relocates it. Before the first quarantine rename, init atomically publishes
and fsyncs `.stdd/cleanup-transaction.json` with each output's original and
quarantine paths, expected hash, and captured parent and file identities.
Every later phase is durably recorded. A manifest-publish failure rolls back
all quarantines; if rollback cannot prove the exact original identities, the
journal remains and the next init deterministically recovers or blocks without
forgetting an orphan. `check` and `doctor` report any pending or malformed
cleanup journal; they never treat it as generated output. The journal is
repo-local, single-linked, owned by the current user, exactly mode `0600`,
and replaced atomically. Journal reads bind metadata, bytes, and the final
pathname to one `O_NOFOLLOW` file descriptor. Recovery rollback opens and
validates the captured parent directory and renames through that held
descriptor; a concurrent logical-parent swap therefore cannot redirect
rollback and leaves an unresolved journal instead. Journal temp creation and
publication use that same held `.stdd` parent, so a swap cannot redirect the
WAL itself. The replacement manifest is committed in durable order:
held-parent temp creation, file fsync, held-parent atomic rename, directory
fsync, then logical-parent and manifest-identity verification. Only after
that proof may the journal be cleared; an indeterminate post-rename failure
leaves it for deterministic recovery. `init` and `configure` currently
require the Linux held-parent pathname bridge; on unsupported platforms they
fail before cleanup-journal recovery or generated install mutation instead
of falling back to an unsafe logical-path rename. The rest of the
method is review discipline — anything that later proves mechanically
checkable should move into `stdd check`.

A repository may declare a worktree-readiness contract in
`.stdd/config.json` — paths that must exist before verification output can
be trusted (installed dependencies, built packages, per-checkout env
files), each with a repo-authored fix hint. `stdd doctor` reports missing
ones; `stdd doctor --readiness` runs only that section, cheap enough for
every session start. The check is purely declarative — stdd verifies and
prescribes, it never installs, and it does not detect a stale-but-present
artifact (freshness belongs to the repo's own build tooling).

A repository may also declare **content rules** in `.stdd/config.json` —
mechanically checkable conventions that would otherwise live in folklore.
Each `contentRules` entry names the rule, a `files` glob, a `forbid`
and/or `require` regex, an optional repo-authored `message`, and
`newFilesOnly: true` to grade only files added against `baseRef`
(without a resolvable base, all matches are graded). `stdd check`
reports hits as violations; `stdd doctor` reports the section's health.
The kit ships the mechanism — the adopting repo authors the rule.

With a `branchPattern` regex in the same config, `stdd check` run on a
branch also validates the branch name — the pre-push hook thus rejects a
doomed name before the forge does. A detached checkout (CI) skips the
rule, and the pattern must match every branch a human pushes, including
long-lived ones (`^(main|dev|feat/|fix/)…`).

A repository also declares a **capability profile** in the same config —
a `capabilities` object stating what the agent environment can actually
do: `subagents` (fresh subagent sessions can be dispatched), `crossCli`
(Claude Code and Codex may invoke each other), `worktrees` (isolated git
worktrees are available). Defaults: `subagents` and `worktrees` on,
`crossCli` off. Playbooks are compiled against the profile at `stdd init`
time, never branched at runtime: a `<!-- cap:NAME --> … <!-- /cap -->`
block survives compilation only when its capability is on (a block
naming alternatives, `cap:a|b`, survives when any of them is on), and a
playbook whose frontmatter declares `requires: NAME` is skipped entirely
when it is off. Edit the profile and re-run `stdd init` — the generated skills
and the AGENTS snippet match the project again, and generated files a
previous init wrote that fall outside the new profile are removed
(only when still byte-identical to what init wrote). `stdd init
--capabilities <list>` writes the profile without hand-editing JSON
(named capabilities on, the rest off), and `stdd init --interview` asks
one question at a time — recommended answer first — then runs the same
init. The interview also picks the reviewer route (`review.via`) and,
for the selected native agents (Claude Code and Codex), offers the Stop hook.
When `crossCli` is selected, the first selected native host is the driver for
the repository-level reviewer default and its opposite CLI is recorded:
Claude → codex, Codex → claude. Per-host generated skills use the same
opposite-host rule explicitly, so a repository compiling both hosts never
teaches either host to review itself. With no dispatch capability, generated
skills omit the `[review:]` claim and review commands entirely; manual
self-review is never presented as an independent-review fallback.

`stdd configure` re-runs the interview over an existing install, with
the **current** values as the defaults. It edits only the capability
profile and the review route — every other config key is preserved —
and recompiles the same generated targets the last init produced (the
manifest remembers them). It does not install or remove CI workflows,
change CI target selection, or remove lifecycle hooks. Stop hooks are the
explicit exception: a remembered Stop-hook target is maintained (and restored
if missing), while `--stop-hook` opts in and may install it for the selected
agents. Configure never adds pre-push or session hooks. Flag forms skip the
questions: `--capabilities <list>`,
`--review-via subagent|codex|claude`, `--max-rounds <n>` (the review
budget; 0 = unlimited), `--stop-hook`. When the profile has a dispatch
capability, an incompatible route (codex or claude without `crossCli`,
subagent without `subagents`) is an error, never a silent downgrade to
self-review. A profile with no dispatch capability may retain a dormant
route because it emits no review claim; invoking or claiming review still
requires an available route.

Agent adapters have two outputs with deliberately different context costs:

- a short, always-on instruction block carrying only repository invariants;
- native, lazily loaded skills carrying the task workflows.

Inline identifiers and adapter metadata share one printable-text boundary
before they reach task state, logs, or generated files. It accepts ordinary
Unicode, including ZWNJ/ZWJ and emoji sequences, but rejects line/control
characters, unpaired surrogate code units, Unicode `Bidi_Control` code points,
and a fixed denylist of invisible or deprecated formatting controls. The
denylist includes soft-hyphen/grapheme-joiner controls, zero-width space,
word/invisible-operator controls, interlinear/shorthand/music formatting
controls, and BOM, so visually identical or reordered text cannot spoof those
outputs without broadly rejecting Unicode format characters.

For Codex (`--tools codex`), init compiles every active playbook to
`.agents/skills/<name>/SKILL.md`, where Codex can select it implicitly from
its description or the user can invoke it explicitly as `$<name>`. Init also
maintains the repo's `AGENTS.md`: the short STDD section is written between
`stdd:begin`/`stdd:end` marker comments. The file is created when absent, the
marked section is replaced in place when present, and content outside the
markers is never touched. The section is also saved to
`.stdd/AGENTS-snippet.md` for manual composition.

For Claude Code (`--tools claude`), the same playbooks compile to
`.claude/skills/<name>/SKILL.md`, invocable as `/<name>` or selected
implicitly. Init maintains the same short invariant block in `CLAUDE.md`,
between the same managed markers, and saves it as
`.stdd/CLAUDE-snippet.md`. `AGENTS.md` and `CLAUDE.md` stay user-owned and
are never manifest-tracked; the generated snippets and native skills are
manifest-tracked. The full method is never injected into every prompt:
always-on files point to `.stdd/method.md`, while skills load their detailed
workflow only when used.

Three routing skills make the main path explicit instead of asking an agent
to infer a workflow from a flat list: `stdd-start-change` classifies first,
opens a task only for repository-changing work, and routes read-only questions
without writing state; `stdd-implement` runs the docs/red/green/verify loop, and
`stdd-finish-change` closes review, evidence, PR checks, and any requested
runtime verification. Specialized playbooks remain independently invocable.

Repo-local generated skills are the team contract and need no plugin. The
optional `plugins/stdd/` Codex bundle distributes the same playbooks for
personal or marketplace installation and adds fail-open lifecycle helpers.
It never owns repository state: its hooks act only when the checkout contains
`.stdd/` and a project-local `@stdd/cli`; init, task state, policy, and CI stay
with the repository. In the STDD source checkout, `npm run build:plugin`
publishes this bundle through Linux's `/proc/self/fd` held-directory bridge;
the build command fails before writing on macOS or Windows. This is a
development-time publication restriction, not a runtime restriction on the
already-built plugin.

Project-specific recipes live in `.stdd/playbooks/local/` — markdown
playbooks with the same frontmatter contract (`name`, `description`,
`when`, optional `requires`), owned by the repository and never
overwritten by `stdd init`. They compile through the same pipeline as
the kit's playbooks — capability blocks included — into each selected host's
native skill registry. Always-on AGENTS/CLAUDE blocks remain a fixed, minimal
router and do not enumerate either kit or project skills. A local recipe that
reuses a kit playbook's `name` replaces it: project knowledge outranks the kit.
Local recipe names must otherwise be unique; init rejects duplicates before
writing generated state and names both conflicting source files.
The three skills named by that router (`stdd-start-change`, `stdd-implement`,
and `stdd-finish-change`) are mandatory; init rejects a profile or local
override that would make one inactive. Other inactive local overrides still
shadow their kit playbook intentionally.

CI integration is an optional transport adapter around provider-neutral CLI
contracts. Every provider runs `stdd check`; a review pipeline pipes its live
PR/MR description to `stdd check-pr - --base <ref>`. CI never attempts to
prove the agent's reasoning or consume the ignored ledger: it grades only
facts derivable from the checkout and review request.

On GitHub, `stdd init --ci github` writes the canonical workflow for these
gates and installs an explicit supported Node runtime. It fetches the PR body
live from the API and re-runs on body edits —
a workflow reading `github.event.pull_request.body` validates a payload
frozen at trigger time, so an edited body is never re-checked and a re-run
replays the stale text. The fetch uses node, not the gh CLI — node is
already required to run stdd, while self-hosted runners often lack gh —
and the step sets `pipefail`, so a failed fetch fails the gate as a fetch
error instead of feeding check-pr an empty body that misreports as a
missing evidence line. `stdd doctor` flags the frozen-payload form, and flags a PR
template carrying an unquoted evidence label at the start of a line, since
its placeholder residue would pass the gate on every PR.

On GitLab, `stdd init --ci gitlab` writes an includeable
`.gitlab/stdd.gitlab-ci.yml` job. It uses the merge-request API to fetch the
live description, pipes it to `check-pr -`, and passes
`CI_MERGE_REQUEST_DIFF_BASE_SHA` as the base. The job enables `pipefail`, so
an API failure fails the gate instead of being mistaken for an empty body.
Same-project pipelines authenticate with the short-lived `CI_JOB_TOKEN`.
Because fork merge-request pipelines normally run in the source project, the
target must allowlist that source for job-token access. A controlled trusted
fork may instead supply a masked and hidden target-project
`STDD_GITLAB_READ_API_TOKEN` with only `read_api`; target credentials are
never safe in an untrusted fork pipeline. Authentication failure names the
required setup instead of pretending fork access is automatic.
`stdd init --ci generic` writes no provider file; it prints and records the
portable command contract for teams to compose into Jenkins, Buildkite, or an
existing pipeline. Provider templates are adapters, never dependencies of
the method or public SDK.

Locally, `stdd init --hooks` writes a pre-push hook that runs exactly one
fast, offline command: `stdd check`. Nothing network-bound belongs in a
hook — a flaky gate's false positives train `--no-verify`. The hook file
is user-owned after generation (like `config.json`, it is not
manifest-tracked and never overwritten), so teams append their own steps.
stdd never touches `.git/`: install it via
`git config core.hooksPath .stdd/hooks`, or call `stdd check` from an
existing hook manager. `stdd doctor` reports whether the hook is wired
up — informationally, never as a failure.

Generated hooks invoke the project-local package offline and name the scoped
package explicitly:
`npm exec --offline --package=@stdd/cli@<generated-version> -- stdd`. They
never ask npm to resolve the unrelated unscoped package `stdd`. Install
`@stdd/cli` as an exact development dependency before wiring hooks. The
`@stdd/cli` source repository is the one dogfood exception: its generated
automation invokes `node "$(git rev-parse --show-toplevel)/cli/stdd.mjs"`
directly, because the checkout being tested is the package source and may not
exist in npm's offline cache yet.

For selected native agents, `stdd init --session-hook` wires the
session-start ritual mechanically. Claude Code and Codex each get one
`SessionStart` hook (`startup|resume|clear|compact`) in their native settings.
The `compact` source is the single context-restoration path; re-init removes
older managed Claude `PostCompact` entries to avoid running the ritual twice,
while preserving unrelated user hooks. Each hook runs `stdd status --local`, which never calls a
forge or the network, so every fresh context opens with local loop state and
the next step already in it — recorded state instead of recall. Hook entries
are merged into existing valid files without duplication. Invalid settings
are left untouched and a manual instruction is printed instead. Codex
project hooks remain subject to Codex's repository trust review.

`stdd init --stop-hook` (opt-in, also offered by the interview and
`stdd configure`) wires the other end of the selected native agents: a
`Stop` hook running the agent-specific `stdd stop-hook` protocol, which
applies the same judgment as `status --gate` when the agent tries to finish.
Broken claims — a
checked-but-unproven `[review:]` item, a changes-requested or stale
verdict — block the stop with the reasons fed back; unfinished work
never does, the same as the gate. The command respects
`stop_hook_active` (a blocked stop is never re-blocked into a loop) and
fails open: an internal error exits zero, because a broken hook must
not trap the session. Claude blocks with exit 2 and stderr; Codex exits 0
with its documented `Stop` continuation JSON (`decision: "block"` plus
`reason`); an empty JSON object allows a clean stop. The Codex boundary accepts
exactly `{}`, or exactly the two keys `decision` and `reason`, where the
decision is `"block"` and the reason is a string with non-whitespace content.
It emits compact JSON without changing valid reason text. Extra or missing
keys, whitespace-only reasons, arrays, primitives, malformed or empty output,
and nonzero child results all fail open as `{}`.
Merging rules match the session hook.

## The session ledger and `stdd status`

The loop's state must not live only in the agent's context window — context
is not durable storage. **Compaction is a trust boundary**: anything that
must survive a session lives in a file, never in conversation memory.

The ledger is that file: `.stdd/ledger.jsonl`, append-only JSONL, one event
per line. It is a working artifact — per checkout, never committed
(`stdd init` adds the ignore rule). A branch is not a task identity: base
branches and long-lived feature branches are reused. `stdd task start
<name>` therefore opens a random task ID and records the existing plan hash
as its baseline; subsequent events carry `taskId`. `stdd task finish`
closes the active task without deleting its evidence, and `stdd task reset`
closes it as abandoned and opens a fresh ID. Starting while another task is
active is an error; finish/reset are explicit so a new session cannot
silently discard another session's work. Reset publishes its two task
boundaries with one same-directory atomic rename. Its exact internal
transaction names (`.ledger-reset-`, `.ledger-prepared-`,
`.ledger-recovered-`, and `.ledger-aborted-`, each followed by 32 lowercase
hex characters and `.tmp`) are owner-only and ignored by checkout/review
snapshots only after that shape is verified. They are deliberately not
hidden by `.gitignore`, so a matching symlink, non-regular or hard-linked
file, foreign owner, non-private mode, or near-miss name remains visible and
is rejected rather than trusted. A trusted stranded active temp is moved to
an inert recovered quarantine under the next ledger lock after an
interruption. Portable randomized retirement is limited to OS-temporary lock
metadata. Repository transaction-temp recovery and abort instead rename
through a validated held `.stdd` directory descriptor on Linux; when that
safe anchor is unavailable, the temp is preserved and the command fails with
an actionable limitation rather than using a replaceable repository
pathname. The reset commit itself uses the same held directory for its
snapshot, active and prepared temps, final ledger publication, and any
settlement. `stdd task reset` therefore requires Linux held-parent support and
fails before transaction-temp creation or ledger mutation when that boundary
is unavailable; ordinary task start, finish, and recorder appends remain
portable.

`stdd status --json` has one stable top-level shape in every lifecycle
state: `state`, `task`, `branch`, `loop`, `slice`, `plan`, `review`, `pr`,
and `next` are always present. Idle state uses explicit empty/null values,
so integrations never need a second response schema.

Readers consider only the current branch's active task. A plan that was
already present when the task started stays invisible until rewritten for
the new task. A closed task makes `stdd status` report `idle`, not the last
task's unfinished state. Branch-only events written by older stdd versions
remain readable as legacy state on a changed working branch, but are ignored
on a clean base branch so old work cannot be injected into a new session.
Recorders invoked without an explicit start keep the legacy behavior for
backward compatibility and tell the user to run `stdd task start`.

Recorders anchor to the repository, never the shell's working directory.
Run from any subdirectory, `stdd docs`/`red`/`verify`/`note` — and the
ledger reads inside `status`, `slice`, `scope`, `evidence`, and
`check-pr` — resolve one root: the git toplevel when it holds `.stdd/`
(or when no `.stdd/` exists yet), otherwise the nearest ancestor holding
`.stdd/`. The root `.stdd/config.json` resolves the same way, so a
`redPattern` applies from anywhere in the tree, and an accidental nested
`apps/*/.stdd/` cannot appear. The explicit directory argument of
`init`, `check`, and `doctor` is unchanged.

Recorders write it at the moment the fact happens:

- `stdd docs <updated-first|checked|not-applicable> [paths…] [--reason <why>]`
  records the docs decision and its reason once, when it is made.
- `stdd red -- <cmd>` and `stdd verify -- <cmd>` run the command, record
  `{cmd, exit, excerpt, snapshot}` verbatim, and pass the exit code through.
  The snapshot binds the fact to the checkout state that produced it. What
  follows `--` is the command and its arguments, never prose: a single
  quoted description is rejected with the corrected form (wrap shell
  constructs in `sh -c`) and records nothing. `red`
  asserts genuine-red (a test-framework failure, not an environment error)
  only when `.stdd/config.json` defines a `redPattern` regex matched against
  the output; otherwise it records `genuine: "unknown"` and warns. A red run
  that exits zero is recorded as not genuine — that is green, not red.
- `stdd note <text>` records free-form handoff context.

The ledger is **advisory input, never a gate by itself**. `stdd check` and
`check-pr` pass or fail exactly as without it; a missing ledger changes
nothing. Derivation replaces reconstruction where a ledger exists:
`stdd evidence` reads the recorded docs decision first — the diff remains
the cross-check, and on contradiction the diff wins and the conflict is
reported; the authored reason for `checked`/`not-applicable` comes from the
ledger instead of being retyped at PR time. `check-pr` adds one advisory
line when the body's evidence label disagrees with the recorded decision.

`stdd status` is the next-step oracle: callable at any moment, it answers
where in the loop this checkout is and what the next step is. Inputs in
order of trust: git (diff against the configured `baseRef`, branch, dirty
state), then the ledger, then the forge when available (`gh` reports the
branch's PR and its check rollup; offline or without `gh` these lines read
"unknown", never an error). Output is one screen ordered as the loop, with
a concrete `next:` suggestion; `--json` emits the same for agents.
`--local` omits the forge lookup unconditionally and is the only form
generated lifecycle hooks call. A red
event that exited zero or was classified `genuine: "no"` never closes red.
The latest docs decision is cross-checked too: `updated-first` must still
name docs in the current diff, while `checked` and `not-applicable` are
contradicted by a canonical-doc change; missing checked paths also stale the
decision.
Implementation is observed only when the checkout changes after the red
snapshot. A passing verify becomes stale after any later checkout change;
`status` asks for a fresh verify instead of displaying historical green as
current proof. Older ledger events without snapshots remain readable but
are explicitly reported as legacy evidence. Timing
leaves the prose: run `stdd status` at session start and before opening a
PR. Once the loop is verified and the plan is exhausted, the closing
review is the named next step ahead of the evidence line — when the
capability profile has a dispatch route on (`subagents` or `crossCli`),
`status` says to dispatch the fresh reviewer explicitly; with both off
the suggestion is omitted rather than degraded to self-review.

## The durable plan and `stdd defer`

A multi-step change needs a plan that survives compaction. Its working copy
is `.stdd/plan.md`: markdown with a checkbox list (`- [ ]` / `- [x]`), one
item per verifiable step, free prose around it. Like the ledger it is a
per-checkout working artifact — `stdd init` adds the ignore rule, and
`stdd check` fails when the plan or the ledger is a tracked file,
regardless of config.

An optional `Mode: inline|delegated` line (the first such line outside
code fences, case-insensitive; any other value reads as absent) records
the execution choice made at planning time, so it survives compaction
with the plan.

`stdd status` reads the plan and reports progress ("4/7 done") plus the
first open item, and the declared mode when the line is present (in
`--json`: `plan.mode`, null when absent). The mode is informational —
it never affects the gate or the stop hook. Once the current pass through the loop is verified and
open items remain, continuing the plan is the named next step — ahead of
drafting the evidence line and opening the PR.

A checkbox is a claim; for test-gated steps the ledger is the proof. An
item carrying a `[red: <substring>]` tag closes only when the current
branch's ledger holds a red event whose recorded command contains the
substring — a run recorded `genuine: "no"` (a green exit or an environment
error) never closes it. Until then the item counts as open even when
checked, and `stdd status` flags it as unproven.

A multi-step plan ends with an **independent review** of the cumulative
diff as its last item when the capability profile has a dispatch route
(`subagents` or `crossCli`). The item is written in at planning time so
the trigger travels with the plan rather than the session's memory. The
review is not a property of delegation — it closes inline work and
delegated work alike, and its reviewer is a fresh context (a read-only
subagent or the other CLI, per the capability profile) that sees the plan
and the diff, never the implementing session's history. With both dispatch
capabilities off, capability compilation omits the review item and closing
review guidance entirely; it never substitutes self-review.

The review item carries a `[review:]` tag, and the tag follows the same
claim-vs-proof rule as `[red:]`: the checkbox is a claim, the ledger is
the proof. Both tags are read from prose only — a backticked
`` `[review:]` `` names the tag as a literal and never gates the item. A tagged item closes only when the branch's newest `review`
event carries an `approved` verdict — recorded by `stdd review`, never
by ticking the box. Approval closes the item directly from the ledger without
rewriting the plan; its checkbox remains user-authored and may stay unchecked.
Until approval the item counts as open, and a checked item is flagged as
unproven.

`stdd defer <text>` records a scope cut for the active task: the text is
appended under the plan's `## Deferred` section, created as needed. It rejects
idle, legacy, and malformed task state before touching the plan, captures the
task and branch before reading it, and rechecks both before publishing, so a
concurrent task or branch switch records the cut nowhere. Appending to a plan
that predates `task start` changes its baseline hash and makes the plan,
including the deferred cut, visible to the active task. Deferred entries never
count toward progress; carry them into the PR description's out-of-scope when
the PR is assembled. The plan stays deletable at any moment — durable rules
flow to the docs edit, rationale and scope decisions to the PR description
(see "Working artifacts are non-canonical by default").

## The closing review and `stdd review`

`stdd review` runs the closing review and records its verdict as ledger
evidence. The route comes from the capability profile and the `review`
config (`{"review": {"via": "codex"}}`, default `subagent`); `--via`
overrides per call. `--via codex` requires the `crossCli` capability,
`--via subagent` requires `subagents` — an unavailable route is an
error, never a silent fall-back to self-review.

Every run starts the same way: the command snapshots the work under
review — a hash over the diff against `baseRef`, the dirty-file state,
and the plan's text with checkbox marks normalized (ticking a box never
stales a review; editing the plan's words does, because the verdict is
a comparison against exactly that specification). The session ledger,
the plan file, and only the exact private internal transaction names
described above are exempt from the diff and dirty state. Recording events
must never invalidate a review, and a SIGKILL-stranded active temp is a
non-authoritative copy recovered under the next ledger lock only after its
owner-only, single-link regular-file shape is validated.
Every other tracked `.stdd/` deliverable (config, generated kit) stays
under review like any other file. An unresolvable base ref aborts the run —
a review of an unavailable diff proves nothing. The command then builds a
**brief** — the plan, a complete changed-file manifest (the diff body
may truncate beyond a size bound; the manifest never does, and it names
every untracked path too — symlinks and other non-regular files carry a
skipped marker, so nothing the reviewer was not told about can exist),
the diff, the contents of untracked regular files
(a new file is part of the change even before `git add`; symlinks are
skipped and large files are read only up to a bound), a **governing
docs** section (the canonical docs are the standing spec: docs changed
in this branch are named as the spec delta to read first, and when none
changed the configured `canonicalDocs` globs are named instead — the
reviewer is read-only in the repository and reads them itself; contents
are never inlined), the review rubric — spec compliance against the
plan first, then code quality graded against named dimensions: needless
duplication where one home for the logic exists, magic numbers and
strings that deserve named constants, loose type contracts at
boundaries, swallowed or blanket-caught errors, tests that assert mocks
instead of behavior, unrequested extras (a finding, not a bonus),
inconsistency with surrounding patterns, and readability: working code
that is badly written is a legitimate blocking finding, not a style
nit — and a
strict output contract: a single JSON object with required `summary` and
`findings` fields. `summary` and every finding's required `message` must be
non-empty printable single lines; ordinary Unicode, including ZWNJ/ZWJ and
emoji, remains valid. Each finding has `severity: blocking | advisory`,
`path` absent or null or a non-empty printable single line, and `line`
absent or null or a positive safe integer. An absent location field is
normalized to null for findings not tied to one location. For a
control-bearing repository path that cannot cross this inline boundary, the
reviewer omits `path` rather than emitting unsafe text. Any wrong field type
or output shape rejects the whole result. The brief is written
outside the repository, in a
private temporary directory with owner-only permissions — it can carry
source contents and must not be world-readable. A `review-request` event
records the route, snapshot, brief hash, and a versioned, lossless identity
for the OS temp root, private directory, and every owned artifact. Codex's
`last-message.txt` is created owner-only before that event and read only
through a descriptor whose identity still matches the request. If the branch
or active task changes
while a CLI reviewer runs, the command records a terminal cancellation
against the captured original request rather than attaching a verdict to
the new context or leaving an orphan request. The cancellation and verdict
paths share the ledger lock, so exactly one terminal outcome wins.

Private-artifact settlement currently requires Linux's held-parent pathname
bridge. Before moving the private directory, STDD verifies the recorded
directory and artifact identities, overwrites each captured file through an
`O_RDWR` descriptor, fsyncs it, truncates it to zero, and fsyncs again. It
then moves the zeroed directory through held parents into an owner-only,
non-loadable OS-temp quarantine with manual-removal guidance. Settlement
never recursively removes the review directory or unlinks a replaceable
final basename. Unknown siblings, changed identities, legacy requests
without complete identity provenance, and unsupported platforms fail closed
before mutation and require explicit operator remediation. This boundary
protects the owner-only/sticky-temp workflow; standard Node/POSIX does not
provide an identity-conditioned rename primitive against a malicious
same-UID namespace racer, so detected replacements are preserved rather than
destructively rolled back.

- `--via codex` dispatches `codex exec --sandbox read-only` itself —
  stdin closed, wall-clock bounded (`--timeout <seconds>`, default
  600) — parses the reviewer's final message, and recomputes the
  snapshot once the runner returns: a checkout that changed while the
  reviewer ran records stale, the same as on submit.
- `--via claude` dispatches `claude -p --safe-mode --tools Read,Glob,Grep --permission-mode dontAsk`
  headless in the same way — brief over stdin, bounded, and tool-enforced read-only — for
  repositories driven from Codex, or as a second perspective; like codex it
  requires the `crossCli` capability.
- `--via subagent` prints the brief path for the orchestrating agent to
  hand to a fresh read-only subagent; the reviewer's JSON comes back via
  `stdd review --result <file|->`, which grades it against the **open
  subagent request**: a snapshot mismatch with the current checkout
  records the result as stale and rejects it, and a CLI-dispatched
  request (codex or claude) can never be completed by `--result` — its
  runner is its only mouth, so a hand-fed file cannot forge its provenance.
  Submitting a result securely settles the private temporary artifacts. An
  abandoned request is cancelled and settled with `stdd review --cleanup`;
  cleanup also reaches an interrupted CLI request and retries settlement
  when a terminal cancellation outlived its private-artifact move.

Repository text inside the brief is untrusted review data, never reviewer
instructions. The brief states this boundary explicitly; instructions found
inside plans, diffs, filenames, or source contents cannot replace the review
contract.

An automated reviewer is evidence, not a security boundary or a substitute
for accountable human review. Read-only tool enforcement limits mutation; it
does not make model judgment infallible or eliminate prompt-injection risk.
Teams choose which changes still require human approval.

The verdict is **derived, never self-declared**: no blocking findings
means `approved`, any blocking finding means `changes-requested`, and a
runner failure, timeout, malformed output, or stale snapshot means
`error` — an `error` is never an approval. The `review` event records
the verdict, the findings, the snapshot, and the runner's exit; exit
codes mirror the verdict (0 approved, 1 changes-requested, 2 error).
On `approved`, that one ledger fact closes the `[review:]` item; no
second plan write can leave the verdict and its projection split across a
crash or write failure. After `changes-requested`: fix the findings and run
`stdd review` again; the newest verdict controls the tag.

A repository may declare a **review budget**:
`{"review": {"maxRounds": 3}}`. Once the branch's ledger holds that
many `changes-requested` verdicts, `stdd review` refuses another
dispatch and says to defer the remaining findings; `--force` spends one
more round deliberately, and `error` verdicts (timeouts, malformed
output) never burn budget. The budget ends the **loop**, never the
judgment: the gate still refuses to bless an unproven claim, so the
honest exit past a spent budget is an unchecked review item plus the
open findings deferred into the PR. The default is unlimited; the knob
exists because unbounded re-review does not converge on a large diff —
a fresh reviewer finds one more, ever-smaller truth every round.

A stale approval (the snapshot differs from the current checkout)
reopens the review everywhere, not just in the gate: `stdd status`
counts the tagged item unproven again and names `stdd review` as the
next step — an approval of a diff nobody can see anymore proves
nothing about the diff that exists now.

`stdd status --gate` folds the review state into an exit code for hooks
and scripts. It exits non-zero when a `[review:]` item is checked but
unproven, when the newest review verdict is `changes-requested` or
`error`, when an `approved` verdict is stale, or when a review claim or
open request needs a route that the capability profile cannot dispatch.
A configured route is otherwise dormant: a profile with neither
`subagents` nor `crossCli` may keep the default route and passes the gate
when it makes no review claim. An unchecked review item on its own never
fails the gate — work in progress remains pushable; the gate judges
claims, not pace.

## Delegating a slice

When an orchestrating session hands a slice of the work to a worker
session, the roles are fixed: the **orchestrator** owns the docs edit, the
commits, and the PR; the **worker** owns red-green inside a declared scope.
The handoff artifact is the ledger, not prose — a worker's chat summary
does not survive compaction, its recorded events do.

The scope is declared before the worker starts: `stdd slice new` with
`--frozen` (globs the slice must not touch) and/or `--allowed` (globs the
slice may touch — anything outside is a violation) writes a `scope` event
carrying the globs and a **baseline** of the checkout at slice start (the
current head plus content hashes of dirty files). Every glob crosses the
same printable-single-line boundary as other persisted identifiers; control,
bidi, and invisible formatting characters are rejected before ledger state
is written, and hostile pre-existing events make status fail closed. The brief itself follows
the delegate-slice playbook; the worker records `docs`/`red`/`verify`
events as it goes, and the orchestrator assembles the PR body from the
ledger.

`stdd scope` is the postflight check, against the baseline rather than a
ref: only **session-introduced** changes count — a change to a frozen
path, or outside the allowed paths, fails. Dirt inherited from before the
slice (a file already modified at baseline, byte-identical now) is
reported separately and never blamed on the slice. A declared slice
exempts only the ledger, plan, and exact shape-validated private internal
transaction names;
tracked config, generated files, and reset-name near misses under `.stdd/`
remain ordinary scope inputs. The same exact exemption boundary applies to
checkout and review snapshots. A declared slice appears in `stdd status`,
which names the postflight as the next step once the loop is complete.

The worker asks its blocking questions before the first edit — not
mid-slice — and ends with exactly one status: `DONE`,
`DONE_WITH_CONCERNS`, `BLOCKED`, or `NEEDS_CONTEXT`. Escalating early is
never penalized: bad work is worse than no work. Briefs and reports
travel as files, never pasted prose — pasted context stays resident in
the orchestrator's window for the rest of the session.

The orchestrator reviews the diff, never the report alone — a stated
rationale never downgrades a finding. Two verdicts, in order: **spec
compliance** (anything missing from the brief, anything extra beyond it —
unrequested work is a finding, not a bonus — anything misunderstood),
then **code quality** on what was built. When subagents are available,
the reviewer is a fresh one that sees the brief, the diff, and the
report — never the orchestrator's session history — and reviews
read-only. A `BLOCKED` or `NEEDS_CONTEXT` slice is not retried
unchanged: add context, split the slice, or take it inline.

## Bug fixes and refactors

- **Bug fix:** reproduce the symptom in a test before editing. Fix the root
  cause, not the symptom.
- **Refactor:** prove behavior preservation with existing tests, typecheck,
  or focused characterization tests. No docs edit needed when behavior and
  contracts are unchanged.

## Style for docs

Concise. Short, direct sentences. Do not omit words that carry meaning. One
rule lives in one document — link, don't duplicate. Canonical docs use the
repository's declared language and describe the **present**. Configure
`temporalPhrases` in that language to flag likely historical narrative; this
is a deliberately simple heuristic, not semantic proof. History usually
belongs in git and PR descriptions. Fenced code blocks and inline code spans
are exempt: a backticked phrase is a literal being named, not narrative — a
doc may state this very rule without tripping it.

## What stdd does not cover

stdd is a process contract, not an engineering standard. Architecture rules,
dependency-injection styles, error-handling policy, tenant/auth/data safety,
and database-migration policy stay in the adopting team's own contract
(typically `AGENTS.md`) and docs tree. stdd tells you *where* such rules
live and *when* they must be written — not what they should say.
