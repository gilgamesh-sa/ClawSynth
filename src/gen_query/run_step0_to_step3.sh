#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

SKILL_HUB_ARGS=("/mnt/d/project/ClawSynth/skills")
WORKSPACE_HUB="/mnt/d/project/ClawSynth/result/syn_data_test_v3/workspace_test"

usage() {
  cat <<'EOF'
Usage:
  bash src/gen_query/run_step0_to_step3.sh [--skill-hub PATH ...] [--workspace-hub PATH]

Options:
  --skill-hub PATH      Override one skill hub. Can be provided multiple times.
  --workspace-hub PATH  Override the workspace hub used by step0-step3.
  -h, --help            Show this help message.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skill-hub)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --skill-hub" >&2
        exit 1
      fi
      SKILL_HUB_ARGS+=("$2")
      shift 2
      ;;
    --workspace-hub)
      if [[ $# -lt 2 ]]; then
        echo "Missing value for --workspace-hub" >&2
        exit 1
      fi
      WORKSPACE_HUB="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

cd "${PROJECT_ROOT}"

STEP0_ARGS=()
STEPX_ARGS=()

for skill_hub in "${SKILL_HUB_ARGS[@]}"; do
  STEP0_ARGS+=(--skill-hub "$skill_hub")
done

if [[ -n "${WORKSPACE_HUB}" ]]; then
  STEP0_ARGS+=(--output "${WORKSPACE_HUB}")
  STEPX_ARGS+=(--workspace-hub "${WORKSPACE_HUB}")
fi

python3 -m src.gen_query.step0_generate_random_workspaces "${STEP0_ARGS[@]}"
python3 -m src.gen_query.step1_generate_queries "${STEPX_ARGS[@]}"
python3 -m src.gen_query.step2_run_benchmark "${STEPX_ARGS[@]}"
python3 -m src.gen_query.step3_persona_rewrite "${STEPX_ARGS[@]}"

echo "step0-step3 completed."
