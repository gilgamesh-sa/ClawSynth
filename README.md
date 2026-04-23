# ClawSynth

Synthetic workspace and query generation toolkit.
![](./assets/logos/ClawSynth.png)
## Reproducible Setup

This project is pinned for Python `3.13.5` and uses `uv` for environment management.

```bash
cp .env.example .env
uv sync --frozen
```

If you do not already have Python `3.13.5` available locally, install it first:

```bash
uv python install 3.13.5
```

## Quick Start

Generate random workspaces:

```bash
uv run python -m src.gen_query.step0_generate_random_workspaces
```

Run the full `gen_query` pipeline:

```bash
uv run bash src/gen_query/run_step0_to_step3.sh
```

Run batch file generation:

```bash
uv run python src/batch_filegen.py run --workspace-hub <workspace_hub> --workspace-base <workspace_base> --results-dir <results_dir> --skills-source <skills_source>
```

Run batch OpenClaw:

```bash
uv run python src/batch_openclaw.py run --workspace-hub <workspace_hub> --workspace-base <workspace_base> --results-dir <results_dir>
```

## Config

Project secrets should stay in the repo-local `.env` file. Start from `.env.example`.
