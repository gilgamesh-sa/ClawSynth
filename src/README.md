[![English](https://img.shields.io/badge/Language-English-blue)](./README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red)](./README.zh-CN.md)

## OpenClaw File Synthesis

`src/batch_filegen.py` reverse-generates the input files required by the queries produced in the `gen_query` stage. It first determines whether each query truly needs pre-existing local files, then invokes OpenClaw together with the `claw-input-file-generator` skill set to generate them.

The script supports four subcommands:

- `run`: execute file synthesis tasks
- `status`: check current progress
- `reset`: clear logs and rerun from scratch next time
- `cleanup`: remove leftover OpenClaw agents

The most common usage is `run`:

```bash
PYTHONUNBUFFERED=1 nohup python src/batch_filegen.py run \
  --workspace-hub /path/to/gen_query_workspace_hub \
  --workspace-base /path/to/filegen_workspace_base \
  --results-dir /path/to/filegen_result \
  --skills-source /path/to/generator_skills \
  --max-domain-parallel 5 \
  > /path/to/filegen_run.log 2>&1 &
```

Prefer absolute paths whenever possible so background OpenClaw processes do not resolve the wrong directories.

### Input Directory Convention

`--workspace-hub` points to the workspace root produced by `gen_query`. The script scans all subdirectories that contain `queries_persona.jsonl` and treats them as workspaces to process.

A typical layout looks like this:

```text
result/
  your_project/
    workspace_hub/
      workspace_001/
        skills/
        tmp_benchmark_queries.jsonl
        queries.jsonl
        queries_persona.jsonl
      workspace_002/
        ...
    workspace_base/
    filegen_result/
```

Where:

- `workspace_hub`: original workspaces produced by the upstream `gen_query` stage
- `workspace_base`: temporary workspace root used by OpenClaw; the script creates one directory per workspace such as `workspace_001_workspace`
- `filegen_result`: conversation traces and summary outputs for the current file-generation run

### Key Arguments

- `--workspace-hub`: required input data directory
- `--workspace-base`: required for `run`; temporary workspace root for OpenClaw
- `--results-dir`: required for `run`; output directory
- `--skills-source`: required for `run`; source directory for file-generation skills
- `--openclaw-model`: OpenClaw model to use; defaults to `GEN_OPENCLAW_MODEL` from `.env`
- `--openclaw-timeout`: timeout per task, default `1200` seconds
- `--max-domain-parallel`: workspace-level concurrency, default `5`
- `--filter-timeout`: pre-filter timeout, default `50` seconds
- `--filter-workers`: pre-filter concurrency, default `1`
- `--env-file`: environment file path, default `.env`

`--skills-source` usually points to the extracted `generator_skills` directory. The script first copies `skills/` from the original workspace into the temporary workspace, then syncs in the file-generation skills from `--skills-source`. If the same skill exists in both places, the version from `--skills-source` overwrites the one already present in the temporary workspace.

### Before Running

Make sure OpenClaw is available and the target models can be called:

```bash
openclaw models list
```

Your `.env` should at least define:

```bash
# OpenClaw model used to generate input files
GEN_OPENCLAW_MODEL=ali-qwen/qwen3.6-plus

# Pre-filter model that decides whether a query needs local input files
FILTER_MODEL=qwen3.6-plus
FILTER_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
FILTER_API_KEY=your_api_key_here
```

If `GEN_OPENCLAW_MODEL`, `FILTER_MODEL`, `FILTER_API_BASE`, or `FILTER_API_KEY` are missing, the script will fail before `run` starts.

### Execution Logic

At a high level, the script does the following:

- read `queries_persona.jsonl` from each workspace
- use `FILTER_MODEL` to pre-filter which queries actually need input files
- mark non-file-dependent queries as `skip`
- sync the original workspace into `workspace_base/<ws_name>_workspace` for the remaining queries
- preserve the workspace's original `skills/` and inject file-generation skills from `--skills-source`
- call OpenClaw so skills such as `claw-input-file-generator` can generate the required files

Concurrency rules:

- workspaces run in parallel
- tasks within the same workspace run serially
- each task starts with a fresh agent and cleans it up immediately after completion

### Outputs

This stage produces two categories of outputs.

Under `workspace_hub/<workspace_name>/`:

- `filegen_log.jsonl`: per-task execution records
- statuses can include `success`, `skip`, `failed`, `timeout`, `error`, and `empty_payloads`

Under `results-dir/`:

- `summary.json`: aggregate statistics for the current run
- `<workspace>/`: one result directory per workspace
- `<workspace>/<session_id>_*.jsonl`: conversation traces copied from OpenClaw sessions

Status meanings:

- `success`: input files were generated successfully
- `skip`: the pre-filter determined the query does not need local files
- `empty_payloads`: OpenClaw ran but did not produce actual files

### Other Subcommands

Check current progress:

```bash
python src/batch_filegen.py status \
  --workspace-hub /path/to/workspace_hub
```

Clear `filegen_log.jsonl` and rerun from scratch next time:

```bash
python src/batch_filegen.py reset \
  --workspace-hub /path/to/workspace_hub
```

Clean up leftover agents:

```bash
python src/batch_filegen.py cleanup \
  --workspace-hub /path/to/workspace_hub
```

Although `cleanup`, `reset`, and `status` share the same argument interface, the critical argument is still `--workspace-hub`, which must match the data batch you are operating on.

## OpenClaw Trace Generation

`src/batch_openclaw.py` batch-runs the prepared queries in `workspace_hub` through OpenClaw. It supports per-domain parallelism, resumable execution, and random skill-pool sampling.

If you need raw upstream model requests and responses rather than only the default OpenClaw session export, you must enable the project's `litellm_config/` setup and route OpenClaw through LiteLLM. Otherwise, the default flow only preserves session traces. See [../litellm_config/README.md](../litellm_config/README.md).

The script also supports four subcommands:

- `run`: execute all trajectory-generation tasks
- `status`: inspect checkpoint progress
- `reset`: clear the checkpoint and rerun from scratch next time
- `cleanup`: remove leftover OpenClaw agents

Typical `run` command:

```bash
PYTHONUNBUFFERED=1 nohup python src/batch_openclaw.py run \
  --workspace-hub /path/to/workspace_hub \
  --workspace-base /path/to/workspace_base \
  --results-dir /path/to/openclaw_result \
  --skills-pool /path/to/skills-selected \
  --max-domain-parallel 20 \
  > /path/to/openclaw_run.log 2>&1 &
```

Again, absolute paths are strongly recommended.

### Input Directory Convention

`--workspace-hub` is the root input directory. The script walks each domain subdirectory and reads its `queries_persona.jsonl`. For each row that contains a `result` field, that field is used as one OpenClaw task message.

A typical layout:

```text
result/
  your_project/
    workspace_hub/
      domain_a/
        queries_persona.jsonl
        ...
      domain_b/
        queries_persona.jsonl
        ...
    workspace_base/
    openclaw_result/
```

Where:

- `workspace_hub`: upstream data including queries, skills, and reverse-generated files; in practice this is often the `--workspace-base` output of the file-generation stage
- `workspace_base`: workspace root used during OpenClaw execution; one workspace is created per domain, such as `domain_a_workspace`
- `openclaw_result`: trajectory outputs, checkpoints, and summary information

### Key Arguments

- `--workspace-hub`: required source data directory
- `--workspace-base`: required for `run`; OpenClaw workspace root
- `--results-dir`: required for `run`; output directory
- `--openclaw-model`: model used by OpenClaw; defaults to `OPENCLAW_MODEL` from `.env`
- `--openclaw-timeout`: timeout per task, default `1200` seconds
- `--max-domain-parallel`: domain-level concurrency, default `5`
- `--skills-pool`: optional extra skill pool
- `--skill-min`: minimum number of randomly sampled skills per run, default `3`
- `--skill-max`: maximum number of randomly sampled skills per run, default `3`
- `--env-file`: environment file path, default `.env`

### Execution Logic

Important runtime characteristics:

- each domain uses its own isolated workspace
- domains run in parallel, but tasks inside one domain run serially
- every task deletes the previous agent and starts from a clean one
- every result is appended to `checkpoint.jsonl`, so reruns can skip finished work

If the process stops midway, rerunning the same `run` command resumes from where it left off.

### Outputs

`--results-dir` usually contains:

- `checkpoint.jsonl`: per-task execution records with statuses such as `success`, `failed`, `timeout`, and `error`
- `summary.json`: aggregate metrics for the current run, including whether execution resumed from a checkpoint
- `<domain>/`: one result directory per domain
- `<domain>/<session_id>_*.jsonl`: conversation traces copied from OpenClaw sessions

For example, one session id may look like `domain_a_task_003`.

### Skill Pool Notes

If `--skills-pool` is provided, the script will:

- remove skills listed in `SKILLS_TO_REMOVE`
- randomly sample skills from `skills-pool` and symlink them into the workspace `skills/` directory
- force-include any skills listed in `REQUIRED_SKILLS`

The current defaults in the script are:

```python
SKILLS_TO_REMOVE: set[str] = {"synthetic-test-files"}
REQUIRED_SKILLS: set[str] = {
}
```

If you want to guarantee certain baseline capabilities, edit `REQUIRED_SKILLS` in `src/batch_openclaw.py`, for example:

```python
REQUIRED_SKILLS: set[str] = {
    "search",
    "ocr",
}
```

Good candidates for required skills are common capabilities such as web search, OCR, and speech-to-text.

### Other Subcommands

Check progress:

```bash
python src/batch_openclaw.py status \
  --workspace-hub /path/to/workspace_hub \
  --workspace-base /path/to/workspace_base \
  --results-dir /path/to/openclaw_result
```

Clear the checkpoint and rerun from scratch:

```bash
python src/batch_openclaw.py reset \
  --workspace-hub /path/to/workspace_hub \
  --workspace-base /path/to/workspace_base \
  --results-dir /path/to/openclaw_result
```

Clean up leftover agents:

```bash
python src/batch_openclaw.py cleanup \
  --workspace-hub /path/to/workspace_hub \
  --workspace-base /path/to/workspace_base \
  --results-dir /path/to/openclaw_result
```

As with the file-generation script, the most important thing is that `--workspace-hub` matches the current batch of data. Otherwise the script cannot correctly determine the domain set.

If you want automatic quality checks after trace generation, continue with [soft_verify/README.md](./soft_verify/README.md). That module uses LiteLLM raw logs, workspace state, and the final agent response to validate each trajectory.
