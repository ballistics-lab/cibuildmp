# The image action.yml itself builds (runs.image below), not the root
# Dockerfile -- deliberately a separate file, not a shared one. GitHub
# Actions builds this from the exact checkout it already pinned (the
# tag/ref a caller's own `uses:` names), so it installs from that local
# checkout (COPY .) rather than a second git+https fetch of the same ref.
# The root Dockerfile pins the opposite way on purpose (an explicit
# --build-arg ref, for a human running it standalone) -- reusing that one
# here would be a real correctness risk: action.yml's own Docker-action
# syntax has no way to pass --build-arg, so a shared file's ref pin would
# have to be a hardcoded default that silently drifts out of sync with
# whatever tag actually triggered this build.
#
# Lives at the repo root, not .github/docker/ alongside entrypoint.sh --
# a real build failure showed why: GitHub's own Docker-action build uses
# *this file's own directory* as the build context, not action.yml's
# directory (`docker build -f <path> <dirname of that path>`, confirmed
# directly from a real failing run's own command line). Filed in
# .github/docker/ instead, `COPY .` here would only ever see that one
# subdirectory's own two files -- silently missing the wheel install and
# failing to find entrypoint.sh at all, both undetectable without an
# actual build (YAML syntax and local shell testing both passed first).
FROM ubuntu:24.04

# Same apt-only prerequisites as the root Dockerfile -- see that file's
# own comment for the full per-package reasoning (D3/M2/D18). Kept in
# sync by hand today; a real drift risk if one changes without the other,
# not automated away here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    ca-certificates \
    curl \
    python3 \
    gcc-multilib \
    gcc-mingw-w64-x86-64 \
    gcc-mingw-w64-i686 \
    libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Installed from this exact checkout, not a git fetch -- the runner
# already checked out the pinned ref before building this Dockerfile, so
# COPY . picks up precisely that ref's own source: no separate network
# round-trip, no version-drift risk. Installed here, at build time, with
# no extras -- the common case, and the whole point of converting this
# action to a Docker image at all (the install cost is paid once, at
# build/cache time, not on every job run). `inputs.extras` is the one
# thing that can't be known at build time; entrypoint.sh reinstalls with
# it, from this same already-COPY'd source, only when a caller actually
# sets that input -- everyone else pays nothing extra for it.
COPY . /opt/cibuildmp
RUN uv tool install /opt/cibuildmp

# `uv tool install` puts the binary at ~/.local/bin -- not on this base
# image's default PATH at all (verified live against the root Dockerfile's
# own identical install step: `which cibuildmp` finds nothing with a bare
# /usr/local/bin:/usr/bin:/bin PATH, the same set a plain, non-login
# container process actually gets).
ENV PATH="/root/.local/bin:${PATH}"

COPY .github/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
