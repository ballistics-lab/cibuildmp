# 0078 — handing the repo to an uncontexted reader is the docs test the suite cannot be

- Status: Implemented (method, and one round of it)
- Related: [0073], [0076], [0077]

## The gap this closes

[0077] made docs drift a failing build for everything with a machine-readable
counterpart: identifiers, option keys, `CIBMP_*` names, repo paths, image
groups, record links, the action pin, three generated tables. It also said
plainly what it cannot check — prose making a *claim* about behaviour — and
left that to "someone reading."

"Someone reading" is not a plan. The people who read this repository already
know it, which is exactly why the false claims survived: an author cannot
notice that a paragraph only makes sense if you already know the answer.

## The method

Hand the repository to a reader with **no context at all** — no explanation of
what was recently changed, no hint about where to look — and ask it to explain
the project back: what the tool is for, how someone uses it, how the action
relates to the CLI, how a build works, where development is heading. Then ask
for the part that matters: every question the repository did not answer, every
place it had to read source instead of docs, everything contradictory, and what
it would still not know if it had to change something tomorrow.

Fix what it found. Repeat.

## What five rounds actually produced

The findings moved, round by round, and the movement is the useful signal:

| Round | Where the drift was |
| --- | --- |
| 1 | **User-facing claims that were false.** "No bare-host path for any target" (three files; `qemu` builds `mpy-cross` on the host). A documented `checksum mismatch` error the tool cannot emit. An error advising a config key the tool rejects. |
| 2 | **Stale docstrings, and two holes in [0077]'s own guards** — the identifier check could not see a *dropped* tag, and a tracker row escaped its check by being indented. |
| 3 | **Docs clean; drift had moved into source comments** — `docker/natmod.Dockerfile` cited in the present tense two records after it was split, `PORT_IMAGES` in a message a *user* sees. The guards' scope was the boundary drift moved past. |
| 4 | **The guard's own design.** `REMOVED_NAMES` is hand-maintained, so it is only as good as someone remembering — proved by finding a name nobody had recorded. Also: the root `cibuildmp.toml` was in no guarded set, and is a live trap. |
| 5 | **A different class entirely**, because this round was given a *task* ("set up cibuildmp for my module, build it, put it on CI, tell me how to install it") rather than a survey. An empty `CIBMP_*` variable silently overriding config — via the standard Actions conditional-env idiom — is not visible to anyone reading; it is only visible to someone writing a workflow. |

Two things follow from that table.

**A survey saturates.** Rounds 3 and 4 ended with the same list of "what I still
would not know", and every item on it was something no documentation can fix:
whether a driver works without running it, what last week's scheduled matrix
did, what another repository's CI is doing today. That is the fixed point —
not zero findings, but findings that are not documentation's to answer.

**A task does not.** Round 5 found a silent data-loss footgun and the absence of
any complete CI workflow — in a CI tool — because it had to *do* something.
The next useful run is another task, and a different one: wiring a build driver
for one of [0053]'s nine portless ports would test `CONTRIBUTING.md` the way
this one tested `README.md`.

## Why the reader must be uncontexted

Every round was given the same neutral prompt and nothing else. Told what to
look for, a reader confirms it; told nothing, it reports where it actually got
stuck. Round 4's best finding was that [0077]'s guard depends on human memory —
a critique of the fix, not the docs, which no prompt aimed at the docs would
have produced.

The corollary is that this cannot be run by whoever just did the work. The
value is entirely in the absence of context.

## What this does not claim

Five rounds is a sample, not a proof. The suite still cannot check behavioural
prose, and a reader with no context still cannot verify anything needing Docker
credentials, push rights, or another repository's state. What changed is that
"someone will notice" now has a procedure attached.

[0053]: 0053-usermod-ports-without-a-build-driver.md
[0073]: 0073-composite-actions-are-a-permanent-legacy-fallback.md
[0076]: 0076-the-mipsel-holdout-is-bclibc-and-wasm3-not-a7p.md
[0077]: 0077-docs-drift-is-a-failing-test-not-a-discipline-problem.md
