# Contributing to cibuildmp

## Read this first

This project has one rule that matters more than any other, and it lives in
[`CLAUDE.md`](CLAUDE.md): **before designing, renaming, or arguing about
anything with an upstream `cibuildwheel` counterpart — selectors,
identifiers, options and their precedence, container invocation, opt-in
behaviour, config layout — install `cibuildwheel` and read the relevant
module yourself.** Four separate pieces of accidental complexity got built
and then had to be torn back out because that step was skipped; `CLAUDE.md`
names each one. Read it before your first PR, not after your first review
comment.

## Dev loop

```console
$ uv sync
$ uv run ruff check src tests
$ uv run ruff format --check src tests
$ uv run pyright src
$ uv run pytest -q
```

This is exactly what `.github/workflows/tests.yml` and `publish.yml`'s own
`build` job run — if all four pass locally, CI's lint/type/test stage will
too. Python floor is 3.11 (`tomllib`); CI itself runs on 3.14.

Most of `pytest`'s own suite runs with no Docker daemon at all. Exercising
a real build — the thing every record in this project insists on before
calling something done — needs one: point `CIBMP_<TARGET>_DOCKER_IMAGE` at
a locally built image (each `docker/*.Dockerfile`'s own header comment
gives the `docker build`/`docker buildx build` command and the env var it
answers to) to test a change against your own image before it's published.
`examples/template` and `examples/wasm2mpy` are real, working modules —
build against one of those rather than inventing a throwaway fixture.

## Making a change

- **A bug fix or small, in-scope addition** — normal PR, tests included.
  Match the file it lands in: this codebase's own comments explain *why*,
  not *what*; keep that ratio in anything you add.
- **Anything that changes what a config key means, what an identifier looks
  like, or how a selector resolves** — this is exactly the territory
  `CLAUDE.md`'s rule above covers. Read the upstream module first, and if
  cibuildmp deliberately diverges, argue why in the record you write (next
  bullet), not in a code comment nobody will re-read once the reasoning is
  forgotten.
- **A real decision, however small** — gets a numbered record. Read
  [`docs/0000-TRACKER.md`](docs/0000-TRACKER.md)'s own "Conventions"
  section for the exact mechanics (numbering, `Status:` lines, how
  supersession is recorded); it is the one place those rules are kept
  current, so this file doesn't restate them. Short version: next unused
  number after the highest one in `docs/records/`, one file under
  `docs/records/NNNN-<slug>.md`, one row added to the tracker's own "Ideas"
  section and its "Record links" list.

## Before you claim something works

This project's own history is full of things that looked right and
weren't until someone actually ran them: a probe that compiled an empty
translation unit and reported a missing toolchain as buildable, an
`--only` flag whose doc comment claimed upstream semantics it didn't
have, a script that silently built zero user modules because a glob
pattern didn't match. "Looks right" and "the tests mock this" are not
"verified" — a real build, run for real, is what every closed record in
`docs/records/` reports, and it is also what caught every bug above
before a consumer did. If Docker isn't reachable in your environment to
run one, say so in the PR rather than reporting success.

## Keep the docs honest

Closing a record updates the tracker's own row — nothing about that
process touches `README.md` automatically. If your change makes a
sentence in `README.md` (or `docs/reference/design.md`,
`docs/reference/open-questions.md`) describe a state that no longer
exists, fix it in the same PR. `CLAUDE.md` documents a real incident this
caused for a consuming repo — grep the narrative docs for the thing you
just changed before you open the PR, not after someone reads the stale
paragraph at face value.

`tests/test_docs.py` now enforces the checkable half of this, so drift in
an identifier, an option key, a `CIBMP_*` name, a repo path, an image
group, a record link or the `@vX.Y.Z` action pin fails the build rather
than waiting to be read. `bin/refresh_docs.py` goes further for the tables
that are pure functions of the resource files — identifier shapes, the
image-group mapping, the toolchain map are generated, not written. Run it
after any change to `resources/build-platforms.toml` or
`resources/pinned_docker_images.toml`; the test tells you if you forgot.

### Never state another repository's status in a living document

This is a rule rather than a test because it is the one class nothing here
can check: no grep in this repo can tell you what `micropython-bclibc`'s CI
does today. It is also, empirically, the class that actually bites — one
tracker row claiming `a7p` kept `unix-mipsel` on a composite action was
false when written, and was copied into `README.md`, `docs/ACTIONS.md`,
`docs/reference/design.md` and a second `README.md` paragraph before anyone
checked the workflow file. Five places, one wrong sentence, and one of the
copies was made *by a change whose purpose was fixing drift* ([0076],
[0077]).

So: which consuming repo has migrated onto what, which one still calls a
composite action, which one is pinned to which version — all of that lives
in `docs/0000-TRACKER.md`'s [0038] row, dated, and nowhere else. A living
document points at that row. Naming a consuming repo is fine when it is an
*example* ("a7p passes `pre_build_command: make fetch-nanopb`"); asserting
its current state is not.

## Where things actually stand

Don't trust this file's (or `README.md`'s) memory of what's implemented —
both go stale between sessions and neither self-corrects.
[`docs/0000-TRACKER.md`](docs/0000-TRACKER.md)'s own "Implemented" vs. "In
progress / Proposed" split is the only status claim worth acting on.

[0038]: docs/records/0038-m5-adopt-in-three-repos.md
[0076]: docs/records/0076-the-mipsel-holdout-is-bclibc-and-wasm3-not-a7p.md
[0077]: docs/records/0077-docs-drift-is-a-failing-test-not-a-discipline-problem.md
