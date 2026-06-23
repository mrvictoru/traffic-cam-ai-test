#!/usr/bin/env bash
set -euo pipefail
python -m trafficcam.cli --mode discover "$@"
