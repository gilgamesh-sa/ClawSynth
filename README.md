[![English](https://img.shields.io/badge/Language-English-blue)](./README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red)](./README.zh-CN.md)

# ClawSynth

<p align="center">
  <img src="./assets/logos/ClawSynth.png" alt="ClawSynth logo" width="400" height="250">
</p>

ClawSynth is a data synthesis and validation project for OpenClaw Agent workflows. It is used to batch-generate executable user queries, synthesize required local input files when a query depends on them, run OpenClaw to produce full conversation trajectories, and optionally validate those trajectories afterward.

The project can be viewed as four stages:

- `Query synthesis`: generate natural-language queries from skill combinations and rewrite them with personas.
- `Reverse file generation`: detect whether a query needs pre-existing local files and synthesize them with OpenClaw.
- `Forward trajectory generation`: run OpenClaw with prepared queries, skills, and input files to produce final trajectories.
- `Post-processing verification`: validate OpenClaw trajectories using raw LiteLLM logs, workspace state, and the final agent response.

Recommended end-to-end flow:

```text
skills
  -> gen_query produces queries_persona.jsonl
  -> batch_filegen backfills required input files
  -> batch_openclaw produces final trajectories
  -> LiteLLM success_events_all.jsonl / OpenClaw session traces
  -> soft_verify produces verification results
```

The `soft_verify` module combines each query, workspace state, and final agent output to generate a verification plan and return `pass`, `review`, or `fail`. See [src/soft_verify/README.md](./src/soft_verify/README.md) for details.

## Environment Setup

This project uses Python `3.13.x` and recommends `uv` for environment management.

If `uv` is not installed yet, install it first. Then run the following from the project root:

```bash
uv python install 3.13.5
uv sync --frozen
```

Create a local `.env` from the example file:

```bash
cp .env.example .env
```

The `.env` file typically needs the following groups of settings:

```bash
# OpenClaw model for forward trajectory generation
OPENCLAW_MODEL=litellm/glm-5-turbo

# OpenClaw model for reverse input-file generation
GEN_OPENCLAW_MODEL=ali-qwen/qwen3.6-plus

# Pre-filter model used before file generation
FILTER_MODEL=qwen3.6-plus
FILTER_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
FILTER_API_KEY=your_api_key_here

# Query generation model
GEN_QUERY_MODEL=glm-5.1
GEN_QUERY_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
GEN_QUERY_API_KEY=your_api_key_here

# soft_verify model
VERIFY_API_KEY=your_api_key_here
VERIFY_MODEL=glm-5
# VERIFY_API_BASE=https://open.bigmodel.cn/api/paas/v4
VERIFY_TIMEOUT_SECONDS=120
VERIFY_SOFT_AGENT_MAX_ROUNDS=20

# soft_verify OCR capability
PADDLEOCR_AISTUDIO_ACCESS_TOKEN=your_paddleocr_aistudio_access_token
```

If you want LiteLLM to capture the raw upstream requests and responses, also follow [litellm_config/README.md](./litellm_config/README.md) and route OpenClaw through the LiteLLM proxy.

Make sure the OpenClaw CLI is available and your models are visible:

```bash
openclaw models list
```

If the model names differ from your local OpenClaw setup, use the output of `openclaw models list` as the source of truth and update `.env` accordingly.

## Prerequisites

There are two kinds of skill bundles that need to be unzipped before running the pipeline.

### Unzip file-generation skills

The zip files in `generator_skills/` are used to synthesize local input files required by generated queries:

```bash
cd generator_skills
unzip claw-input-file-generator.zip
cd ..
```

You should then see:

```text
generator_skills/
  claw-input-file-generator/
    SKILL.md
    ...
```

### Unzip regular skills

The zip files in `skills/` are the regular skills used during query generation and OpenClaw execution:

```bash
cd skills
unzip excel-xlsx-1.0.2.zip
unzip multi-search-engine-2.1.3.zip
unzip ocr-local-1.0.0.zip
unzip polymarket-trade-1.0.6.zip
unzip weather-1.0.0.zip
cd ..
```

Each extracted skill directory should contain a `SKILL.md`. If the directories already exist, you do not need to unzip them again.

You can also add more usable skills to diversify the sampled data.

## Repository Layout

```text
.
├── README.md
├── README.zh-CN.md
├── .env.example
├── pyproject.toml
├── uv.lock
├── skills/
├── generator_skills/
├── litellm_config/
├── src/
│   ├── README.md
│   ├── README.zh-CN.md
│   ├── batch_filegen.py
│   ├── batch_openclaw.py
│   ├── soft_verify/
│   │   ├── README.md
│   │   ├── README.zh-CN.md
│   │   ├── step1_plan.py
│   │   ├── step2_evaluate.py
│   │   └── ...
│   └── gen_query/
│       ├── README.md
│       ├── README.zh-CN.md
│       ├── config.py
│       ├── run_step0_to_step3.sh
│       ├── step0_generate_random_workspaces.py
│       ├── step1_generate_queries.py
│       ├── step2_run_benchmark.py
│       └── step3_persona_rewrite.py
└── result/
```

Important files and directories:

- `src/gen_query/README.md`: detailed guide for the query synthesis stage.
- `src/README.md`: detailed guide for reverse file generation and forward OpenClaw trajectory generation.
- `src/soft_verify/README.md`: detailed guide for trajectory verification, including LiteLLM log processing and the two-step evaluation flow.
- `litellm_config/README.md`: LiteLLM proxy setup for preserving raw model requests and responses.
- `src/gen_query/config.py`: main configuration entry for query synthesis, including workspace count, skill sampling, and random seeds.
- `src/gen_query/run_step0_to_step3.sh`: one-command runner for steps 0 through 3 of query synthesis.
- `src/batch_filegen.py`: reverse generation of local input files.
- `src/batch_openclaw.py`: forward generation of OpenClaw conversation traces.
- `skills/`: regular skill pool for query generation and OpenClaw execution.
- `generator_skills/`: skills dedicated to file synthesis.
- `result/`: recommended output location for workspaces, file-generation results, and OpenClaw trajectories.

## Quick Start

Below is a recommended flow from query synthesis to trajectory verification. Adjust the paths for your own experiment names, and prefer absolute paths when possible.

### 1. Generate queries

First review the sampling-related parameters in `src/gen_query/config.py`, such as:

- `WORKSPACES_TO_BUILD`
- `MIN_SKILLS_PER_WORKSPACE`
- `MAX_SKILLS_PER_WORKSPACE`
- `QUERIES_PER_SKILL`
- `BENCH_CONCURRENCY`
- `REWRITE_WORKERS`

Then run:

```bash
uv run bash src/gen_query/run_step0_to_step3.sh \
  --skill-hub ./skills \
  --workspace-hub ./result/syn_data_test_v2/workspace_test
```

After completion, each workspace will contain:

```text
tmp_benchmark_queries.jsonl
queries.jsonl
queries_persona.jsonl
```

The `queries_persona.jsonl` file is the query input used by later stages.

### 2. Reverse-generate input files

Some queries ask the agent to work with local images, audio, documents, spreadsheets, or other files. This stage first filters the queries that truly need files, then uses OpenClaw to synthesize them.

```bash
PYTHONUNBUFFERED=1 nohup uv run python src/batch_filegen.py run \
  --workspace-hub ./result/syn_data_test_v2/workspace_test \
  --workspace-base ./result/syn_data_test_v2/filegen_workspace \
  --results-dir ./result/syn_data_test_v2/filegen_result \
  --skills-source ./generator_skills \
  --max-domain-parallel 5 \
  > ./result/syn_data_test_v2/filegen_run.log 2>&1 &
```

This stage expects the following `.env` settings:

- `GEN_OPENCLAW_MODEL`
- `FILTER_MODEL`
- `FILTER_API_BASE`
- `FILTER_API_KEY`

When it finishes, the next stage should usually point `--workspace-hub` to this stage's `--workspace-base`, because the generated input files are written into the temporary filegen workspaces.

### 3. Generate forward OpenClaw traces

Run OpenClaw with the queries, skills, and synthesized input files to produce the final conversation traces:

```bash
PYTHONUNBUFFERED=1 nohup uv run python src/batch_openclaw.py run \
  --workspace-hub ./result/syn_data_test_v2/filegen_workspace \
  --workspace-base ./result/syn_data_test_v2/openclaw_workspace \
  --results-dir ./result/syn_data_test_v2/openclaw_result \
  --skills-pool ./skills \
  --max-domain-parallel 5 \
  > ./result/syn_data_test_v2/openclaw_run.log 2>&1 &
```

This stage requires:

- `OPENCLAW_MODEL`

If you want the raw upstream model requests and responses instead of only the final session trace files, you must enable `litellm_config/` and let OpenClaw call the model through LiteLLM. Otherwise you will only get the default OpenClaw session export. See [litellm_config/README.md](./litellm_config/README.md).

With LiteLLM enabled, the raw capture is appended to `litellm_config/success_events_all.jsonl`. To convert it into a more readable conversation format, run:

```bash
uv run python src/process_data/process_conversations.py \
  --input_file ./litellm_config/success_events_all.jsonl \
  --output_file ./litellm_config/message.jsonl
```

The processed `litellm_config/message.jsonl` file is easier to inspect and reuse in later processing.

The output of this stage is stored in `--results-dir`, including:

- `checkpoint.jsonl`
- `summary.json`
- OpenClaw session trace files under each workspace or domain directory

### 4. Post-process and verify traces

If you want automated checks for the forward-generated traces, continue with the `soft_verify` module. This stage depends on the raw logs captured by LiteLLM, so it is best to enable LiteLLM during forward trajectory generation.

First, normalize the raw LiteLLM logs and extract them into the unified verification input format:

```bash
uv run python src/process_data/process_conversations.py \
  --input_file ./litellm_config/success_events_all.jsonl \
  --output_file ./litellm_config/message.jsonl

uv run python src/process_data/extract_for_check.py \
  --input_file ./litellm_config/message.jsonl \
  --workspace_hub_dir ./result/syn_data_test_v2/filegen_workspace \
  --workspace_base ./result/syn_data_test_v2/openclaw_workspace \
  --output_file ./result/syn_data_test_v2/tasks_for_check.jsonl
```

Then run the two verification steps:

```bash
uv run python src/soft_verify/step1_plan.py \
  --input ./result/syn_data_test_v2/tasks_for_check.jsonl \
  --output ./result/syn_data_test_v2/step1_output.jsonl \
  --workers 8

uv run python src/soft_verify/step2_evaluate.py \
  --input ./result/syn_data_test_v2/step1_output.jsonl \
  --output ./result/syn_data_test_v2/step2_output.jsonl \
  --workers 8
```

The final output contains fields such as `verdict`, `score`, and `llm_check_results`. See [src/soft_verify/README.md](./src/soft_verify/README.md) for the full verification workflow.

## Useful Commands

Check reverse file-generation progress:

```bash
uv run python src/batch_filegen.py status \
  --workspace-hub ./result/syn_data_test_v2/workspace_test
```

Clean up leftover reverse file-generation agents:

```bash
uv run python src/batch_filegen.py cleanup \
  --workspace-hub ./result/syn_data_test_v2/workspace_test
```

Check forward trajectory generation progress:

```bash
uv run python src/batch_openclaw.py status \
  --workspace-hub ./result/syn_data_test_v2/filegen_workspace \
  --workspace-base ./result/syn_data_test_v2/openclaw_workspace \
  --results-dir ./result/syn_data_test_v2/openclaw_result
```

Clean up leftover forward trajectory generation agents:

```bash
uv run python src/batch_openclaw.py cleanup \
  --workspace-hub ./result/syn_data_test_v2/filegen_workspace \
  --workspace-base ./result/syn_data_test_v2/openclaw_workspace \
  --results-dir ./result/syn_data_test_v2/openclaw_result
```

## More Documentation

For deeper stage-specific details, see:

- [src/gen_query/README.md](./src/gen_query/README.md)
- [src/README.md](./src/README.md)
- [litellm_config/README.md](./litellm_config/README.md)
- [src/soft_verify/README.md](./src/soft_verify/README.md)

If you rerun any stage, double-check its output directory, logs, and checkpoint behavior first so you do not mix artifacts from different experiments.
