[![English](https://img.shields.io/badge/Language-English-blue)](./README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red)](./README.zh-CN.md)

# Synthesizer Query Generation

This directory corresponds to the query-synthesis stage of the project: it generates queries from sampled skill combinations, rewrites them with personas, and finally produces `queries_persona.jsonl` for later OpenClaw trajectory generation.

## Overall Flow

The pipeline is split into four steps:

- `step0_generate_random_workspaces.py`
  Randomly sample skills from one or more skill hubs and generate a batch of workspaces.
- `step1_generate_queries.py`
  Read the `skills/` directory inside each workspace, generate query prompts for each skill, and write `tmp_benchmark_queries.jsonl`.
- `step2_run_benchmark.py`
  Call an OpenAI-compatible API to turn the prompts from step 1 into raw queries in `queries.jsonl`.
- `step3_persona_rewrite.py`
  Rewrite the step 2 queries with personas and write the final `queries_persona.jsonl`.

The deliverable from this stage is the `queries_persona.jsonl` file inside each workspace.

## Project Structure

- `src/gen_query/config.py`
  Main configuration entry point for steps 0 through 3.
- `src/gen_query/run_step0_to_step3.sh`
  One-command script that runs step 0 through step 3 sequentially.
- `src/gen_query/utils/`
  Shared utilities, including workspace scanning, JSONL helpers, and LLM calls.
- `src/gen_query/data/unique_task_instructions.json`
  Persona instruction pool used in step 3.

## Input and Output Directory Convention

`WORKSPACE_HUB` is the core working directory for this sub-pipeline. Step 0 creates workspaces there, and steps 1 through 3 keep writing intermediate and final artifacts back into those workspaces.

Example layout:

```text
result/
  syn_data_test_v2/
    workspace_test/
      workspace_test001/
        skills/
          some-skill/
            SKILL.md
        tmp_benchmark_queries.jsonl
        queries.jsonl
        queries_persona.jsonl
      workspace_test002/
        ...
```

Two naming rules are worth noting:

- `WORKSPACE_HUB` is the workspace root, such as `result/syn_data_test_v2/workspace_test`
- each workspace is named like `${WS_PREFIX}001`, `${WS_PREFIX}002`, not a fixed `workspace_001`

## Configuration

Most configuration lives in `src/gen_query/config.py`, but model settings are intentionally not hardcoded there. They are read from the project root `.env` first:

```bash
GEN_QUERY_MODEL=glm-5.1
GEN_QUERY_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
GEN_QUERY_API_KEY=your_api_key_here
```

In practice:

- paths, sampling scale, and persona files are mainly configured in `config.py`
- model name, API base, and API key are best kept in the project root `.env`

## Core Settings

### Step 0: workspace generation

- `SKILL_HUBS`
  List of skill hubs. Step 0 scans subdirectories that directly contain `SKILL.md`.
- `WORKSPACE_HUB`
  Workspace root directory.
- `WS_PREFIX`
  Prefix for workspace directory names.
- `WORKSPACES_TO_BUILD`
  Number of workspaces to generate.
- `MIN_SKILLS_PER_WORKSPACE`
  Minimum number of sampled skills per workspace.
- `MAX_SKILLS_PER_WORKSPACE`
  Maximum number of sampled skills per workspace.
- `WORKSPACE_COPY_MODE`
  How skills are placed into workspaces: `symlink` or `copy`.
- `WORKSPACE_FORCE_CLEAN`
  Whether to clear the output directory before step 0 starts.
- `RANDOM_SEED`
  Random seed controlling sampling and some prompt randomness.

### Step 1: prompt generation

- `QUERIES_PER_SKILL`
  Number of query prompts generated for each skill.

Step 1 produces prompt records, not final queries. The output file is `tmp_benchmark_queries.jsonl`.

### Step 2/3: LLM generation and persona rewrite

- `LITELLM_MODEL`
  Model used for query generation and persona rewriting, read from `.env`.
- `LITELLM_API_BASE`
  Model endpoint, read from `.env`.
- `LITELLM_API_KEY`
  Model API key, read from `.env`.
- `BENCH_CONCURRENCY`
  Concurrency for raw query generation in step 2.
- `REWRITE_WORKERS`
  Concurrency for persona rewriting in step 3.
- `REWRITE_TIMEOUT`
  Per-record timeout for step 3.
- `INSTRUCTIONS_FILE`
  Persona instruction pool file.

## Recommended Ways to Run

The simplest option is:

```bash
bash src/gen_query/run_step0_to_step3.sh
```

If you do not want to change the default paths inside the script, override them on the command line:

```bash
bash src/gen_query/run_step0_to_step3.sh \
  --skill-hub /path/to/skills \
  --workspace-hub /path/to/workspace_hub
```

Notes:

- `--skill-hub` can be passed multiple times to add more skill hubs
- `--workspace-hub` overrides the workspace root used by steps 0 through 3

If you prefer running each step manually, you can also execute them individually:

```bash
python3 -m src.gen_query.step0_generate_random_workspaces --output /path/to/workspace_hub
python3 -m src.gen_query.step1_generate_queries --workspace-hub /path/to/workspace_hub
python3 -m src.gen_query.step2_run_benchmark --workspace-hub /path/to/workspace_hub
python3 -m src.gen_query.step3_persona_rewrite --workspace-hub /path/to/workspace_hub
```

## Pre-run Checklist

Before starting, verify that:

- `SKILL_HUBS` or `--skill-hub` points to valid directories whose subdirectories contain `SKILL.md`
- `WORKSPACE_HUB` or `--workspace-hub` points to the intended output location
- `WORKSPACES_TO_BUILD`, `MIN_SKILLS_PER_WORKSPACE`, and `MAX_SKILLS_PER_WORKSPACE` match your experiment scale
- the project root `.env` already contains `GEN_QUERY_MODEL`, `GEN_QUERY_API_BASE`, and `GEN_QUERY_API_KEY`
- `INSTRUCTIONS_FILE` points to a valid persona JSON file

## Outputs by Stage

- step0
  creates workspace directories like `${WORKSPACE_HUB}/${WS_PREFIX}001` and initializes `skills/`
- step1
  writes `tmp_benchmark_queries.jsonl` inside each workspace
- step2
  writes `queries.jsonl` inside each workspace
- step3
  writes `queries_persona.jsonl` inside each workspace

## Result File Notes

### `tmp_benchmark_queries.jsonl`

This file contains the prompts produced in step 1 and consumed by step 2. It usually includes:

- `id`
- `workspace`
- `skills`
- `skill_main`
- `type`
- `input_style`
- `query`

Here, `query` is still the full model prompt, not the final user query.

### `queries.jsonl`

This is the raw query output from step 2. In your current artifacts, one record roughly looks like:

```json
{
  "id": "workspace_test001__weather-1.0.0_01",
  "workspace": "workspace_test001",
  "skills": ["weather-1.0.0"],
  "skill_main": "weather-1.0.0",
  "type": "file",
  "input_style": "explicit",
  "query": "...prompt sent to the model ...",
  "result": "Please check the weather in Xining for the next three days, then use the daylight and meteorological data to write a short note about recent photovoltaic power generation impact and save it to `./photovoltaic_weather_analysis_83241.md`"
}
```

The actual query used by later stages is stored in the `result` field.

### `queries_persona.jsonl`

This is the final output file from step 3. It preserves the original record and adds persona-rewritten content. For example:

```json
{
  "id": "workspace_test001__weather-1.0.0_01",
  "workspace": "workspace_test001",
  "skills": ["weather-1.0.0"],
  "result": "Hello! I've been really busy lately. Could you help me with this when you have a moment?...",
  "result_original": "Please check the weather in Xining for the next three days, then use the daylight and meteorological data...",
  "persona": "You are polite, optimistic, busy."
}
```

You can treat this file as the final deliverable:

- `result` is the persona-rewritten query
- `result_original` is the original step 2 query
- `persona` is the persona applied to that sample

## Additional Notes

- step0 samples random skill combinations from the skill hub by default
- step1 generates multiple prompt styles, such as `file/chat` and `explicit/vague`
- if you only care about the final deliverable, focus on the `queries_persona.jsonl` files under each workspace
