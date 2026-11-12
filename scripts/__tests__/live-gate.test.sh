#!/usr/bin/env bash
# The post-deploy live gate must be RED on a trial form with internal names and GREEN on a clean page
# (fixtures only, no network). Patrik TG 5607, 2026-11-12.
set -u
HERE="$(cd "$(dirname "$0")/.." && pwd)"
node "$HERE/live-gate/selftest.mjs"
