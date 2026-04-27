[![English](https://img.shields.io/badge/Language-English-blue)](./README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red)](./README.zh-CN.md)

# soft_verify

`soft_verify` is the ClawSynth module used to validate the quality of OpenClaw conversation trajectories. Its goal is not to check whether the model followed a rigid fixed template. Instead, it combines:

- the user query
- the file state inside the corresponding workspace
- the final agent response

to generate executable validation checks, then lets a tool-enabled verification agent score those checks and return a final `pass`, `review`, or `fail`.

The current implementation is intentionally lenient and works well for large-scale data cleaning, spot checks, and initial filtering. If you need stricter evaluation, tighten the prompts, thresholds, or tool logic.

## Verification Flow Overview

The full pipeline has four steps:

1. Capture raw logs from the OpenClaw forward-generation stage through LiteLLM.
2. Normalize the raw logs into a more stable conversation format.
3. Extract `intent`, `workspace`, and `agent_final_output` into a unified verification input.
4. Run `step1_plan.py` and `step2_evaluate.py` to get the final verdict.

Recommended flow:

```text
OpenClaw forward trajectory generation
  -> LiteLLM success_events_all.jsonl
  -> process_conversations.py produces message.jsonl
  -> extract_for_check.py produces tasks.jsonl
  -> step1_plan.py produces plan.jsonl
  -> step2_evaluate.py produces result.jsonl
```

## Before You Run

### 1. Main project environment

The dependencies for `soft_verify` are already included in the main project's `pyproject.toml`. From the repository root, run:

```bash
uv sync
```

It is recommended to run all later commands from the repository root and use the shared `uv` environment.

### 2. Environment variables

At minimum, configure:

```bash
# Verification model
VERIFY_API_KEY=your_api_key_here
VERIFY_MODEL=glm-5
# VERIFY_API_BASE=https://open.bigmodel.cn/api/paas/v4
VERIFY_TIMEOUT_SECONDS=120
VERIFY_SOFT_AGENT_MAX_ROUNDS=20

# OCR capability
PADDLEOCR_AISTUDIO_ACCESS_TOKEN=your_paddleocr_aistudio_access_token
```

Where:

- `VERIFY_*` is used to generate verification plans and run the soft-check agent
- `PADDLEOCR_AISTUDIO_ACCESS_TOKEN` is used when verification needs to read text from images or PDFs

You can obtain the OCR token from the Baidu AI Studio documentation: `https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma`

### 3. LiteLLM raw logs

If you did not enable LiteLLM to capture the raw upstream requests and responses, this verification workflow cannot run.

For setup details, see [../../litellm_config/README.md](../../litellm_config/README.md).

The raw input file required by the verification flow is:

```text
litellm_config/success_events_all.jsonl
```

This file contains the raw LiteLLM capture.

## Prepare Input Data

### Step 1: normalize the LiteLLM raw trace

Convert `success_events_all.jsonl` into a more readable and stable conversation format:

```bash
uv run python src/process_data/process_conversations.py \
  --input_file ./litellm_config/success_events_all.jsonl \
  --output_file ./litellm_config/message.jsonl
```

Output file:

```text
litellm_config/message.jsonl
```

### Step 2: convert into the unified soft_verify input format

Then convert the conversation trace into the format expected by `soft_verify`:

```bash
uv run python src/process_data/extract_for_check.py \
  --input_file ./litellm_config/message.jsonl \
  --workspace_hub_dir ./result/syn_data_test_v2/workspace_test \
  --workspace_base ./result/syn_data_test_v2/openclaw_workspace \
  --output_file ./result/syn_data_test_v2/tasks_for_check.jsonl
```

Argument notes:

- `--input_file`: the `message.jsonl` created in the previous step
- `--workspace_hub_dir`: the upstream query `workspace_hub`
- `--workspace_base`: the real `workspace_base` used when forward trajectories were generated
- `--output_file`: output JSONL consumed by `soft_verify`

Two details matter a lot here:

- `--workspace_hub_dir` and `--workspace_base` must match the directories used by the actual OpenClaw run you want to verify
- if those paths are wrong, the workspace snapshot seen during verification will be inaccurate

Each output row roughly looks like:

```json
{
  "intent": "user query text",
  "workspace": "/abs/path/to/workspace",
  "agent_final_output": "final agent response"
}
```

## Run Verification

Verification is split into two steps.

### Step 1: generate the verification plan

`step1_plan.py` uses `intent`, `workspace`, and `agent_final_output` to generate a list of `llm_checks` for the later verification agent.

```bash
uv run python src/soft_verify/step1_plan.py \
  --input ./result/syn_data_test_v2/tasks_for_check.jsonl \
  --output ./result/syn_data_test_v2/step1_output.jsonl \
  --workers 8
```

Common arguments:

- `--input`: unified input JSONL from the previous step
- `--output`: output file for the verification plan
- `--workers`: worker concurrency, default `8`
- `--path-mode`: path resolution mode, default `auto`

Supported `--path-mode` values:

- `auto`
- `workspace-only`
- `absolute-priority`

In most cases, the default `auto` is fine.

Core fields in the output include:

- `intent`
- `workspace`
- `agent_final_output`
- `llm_checks`

If a row fails during step 1, the output still keeps the failed record together with its error details for later debugging.

### Step 2: execute the checks and score the result

`step2_evaluate.py` reads the `llm_checks` from step 1, runs a tool-enabled verification agent, and outputs the final score and verdict.

```bash
uv run python src/soft_verify/step2_evaluate.py \
  --input ./result/syn_data_test_v2/step1_output.jsonl \
  --output ./result/syn_data_test_v2/step2_output.jsonl \
  --workers 8
```

Common arguments:

- `--input`: output from `step1_plan.py`
- `--output`: final verification result file
- `--workers`: worker concurrency, default `8`
- `--path-mode`: path resolution mode, default `auto`

The final result typically includes:

- `verdict`
- `score`
- `llm_check_results`

## Additional Notes

- This workflow depends on LiteLLM raw logs, so it is best to enable LiteLLM during OpenClaw forward trajectory generation.
- If you only have OpenClaw session traces and do not have `success_events_all.jsonl`, this workflow cannot run end to end.
- If you want to make the evaluation stricter over time, the best starting points are the prompts and thresholds in `step1_plan.py` and `step2_evaluate.py`.
