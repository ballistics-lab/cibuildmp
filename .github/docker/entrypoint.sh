#!/bin/bash
# Docker container actions get their inputs as INPUT_<NAME> env vars, name
# uppercased -- but GitHub's own docs only say spaces become `_`, not
# dashes, and this action's own inputs (package-dir, output-dir,
# config-file) all have dashes. So the real env var names are
# INPUT_PACKAGE-DIR / INPUT_OUTPUT-DIR / INPUT_CONFIG-FILE, which cannot
# be referenced as a plain $VAR (a literal `-` there breaks normal
# variable-name syntax) -- `printenv NAME` is the portable way to read one
# regardless.
#
# Must be bash, not /bin/sh (dash on this image): verified live that dash
# silently drops any inherited env var whose name isn't a valid POSIX
# shell identifier when it forks a child -- it reconstructs each child's
# environment from its own internal "imported variables" table rather
# than forwarding the raw inherited environ, and a hyphenated name never
# makes it into that table at dash's own startup. `printenv
# 'INPUT_PACKAGE-DIR'` run *from* a dash script silently returns nothing
# for exactly that reason, even though the variable is genuinely present
# in dash's own process environment (confirmed via /proc/$$/environ) --
# bash does not have this limitation, and was checked to actually work
# for this exact case before relying on it here.
#
# Mirrors action.yml's own composite-action shell step exactly: same five
# inputs, same "only pass a flag when the input is actually set"
# behavior, same MODULE_DIR positional-first argument.
set -eu

pkg_dir=$(printenv 'INPUT_PACKAGE-DIR' 2>/dev/null || true)
out_dir=$(printenv 'INPUT_OUTPUT-DIR' 2>/dev/null || true)
cfg_file=$(printenv 'INPUT_CONFIG-FILE' 2>/dev/null || true)
only=$(printenv 'INPUT_ONLY' 2>/dev/null || true)
extras=$(printenv 'INPUT_EXTRAS' 2>/dev/null || true)

# extras can't be known at image-build time (action.Dockerfile's own
# comment) -- reinstall from the same already-COPY'd source, with them,
# only when a caller actually sets this input. Everyone else never hits
# this branch.
if [ -n "$extras" ]; then
    uv tool install "/opt/cibuildmp[${extras}]"
fi

set -- "${pkg_dir:-.}"
if [ -n "$out_dir" ]; then
    set -- "$@" --output-dir "$out_dir"
fi
if [ -n "$cfg_file" ]; then
    set -- "$@" --config-file "$cfg_file"
fi
if [ -n "$only" ]; then
    set -- "$@" --only "$only"
fi

exec cibuildmp "$@"
