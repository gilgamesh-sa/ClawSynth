[![English](https://img.shields.io/badge/Language-English-blue)](./README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red)](./README.zh-CN.md)

## LiteLLM Gateway Capture

This directory is used to proxy large-model requests through LiteLLM and record the raw requests and responses generated when OpenClaw calls the model.

OpenClaw by itself usually does not expose the full low-level conversation payloads. With LiteLLM in front, the raw data is written to `success_events_all.jsonl` for later analysis.

## Directory Overview

- `litellm_config.yaml.example`
  Template LiteLLM proxy configuration.
- `litellm_config.yaml`
  Your actual local LiteLLM configuration.
- `custom_callbacks.py`
  Custom callback logic. It currently appends successful requests to a JSONL log.
- `success_events_all.jsonl`
  LiteLLM success log containing raw requests and responses.
- `litellm.log`
  LiteLLM startup and runtime log.

## Install LiteLLM in the uv Environment

This project recommends using `uv` consistently. The callback script in this directory depends on:

- `litellm`
- `aiofiles`

Install them from the project root:

```bash
uv add litellm aiofiles
```

If you only want to sync dependencies that are already declared, you can instead run:

```bash
uv sync
```

Then verify that LiteLLM is available inside the current `uv` environment:

```bash
uv run litellm --help
```

If that command prints the help text successfully, LiteLLM is installed correctly.

## Configure LiteLLM

Start by copying the template:

```bash
cp litellm_config/litellm_config.yaml.example litellm_config/litellm_config.yaml
```

Edit `litellm_config/litellm_config.yaml` and at minimum configure:

- `model_list`
  The models you want the proxy to expose to OpenClaw.
- `api_key`
  The real upstream API key.
- `api_base`
  The upstream model endpoint.
- `master_key`
  The access key used by LiteLLM itself.

Current template example:

```yaml
model_list:
  - model_name: glm-5.1
    litellm_params:
      model: openai/glm-5.1
      api_key: api_key
      api_base: https://open.bigmodel.cn/api/paas/v4
      extra_body:
        enable_thinking: true
  - model_name: glm-5-turbo
    litellm_params:
      model: openai/glm-5-turbo
      api_key: api_key
      api_base: https://open.bigmodel.cn/api/paas/v4
      extra_body:
        enable_thinking: true

litellm_settings:
  master_key: sk-litellm-master-key
  callbacks: custom_callbacks.proxy_handler_instance
  drop_params: True

general_settings:
  host: "127.0.0.1"
  port: 2013
  log_level: "debug"
  cors: True
```

## Start the LiteLLM Gateway

The recommended commands from the project root are:

```bash
cd litellm_config
nohup ../.venv/bin/litellm --config litellm_config.yaml --port 2013 > litellm.log 2>&1 &
cd ..
```

If you do not want to rely on a fixed `.venv` path, you can use `uv run` instead:

```bash
cd litellm_config
nohup uv run litellm --config litellm_config.yaml --port 2013 > litellm.log 2>&1 &
cd ..
```

After startup, inspect the log to confirm the service is healthy:

```bash
tail -f litellm_config/litellm.log
```

Output like the following usually indicates success:

```bash
Uvicorn running on http://0.0.0.0:2013
POST /v1/chat/completions HTTP/1.1" 200 OK
```

## Configure OpenClaw to Use LiteLLM

Next, update OpenClaw so it calls the local LiteLLM gateway instead of the upstream provider directly.

You need to edit two places in `.openclaw/openclaw.json`.

### 1. Register a LiteLLM provider under `models.providers`

Example:

```json
{
  "models": {
    "mode": "merge",
    "providers": {
      "litellm": {
        "baseUrl": "http://127.0.0.1:2013/v1",
        "apiKey": "sk-litellm-master-key",
        "api": "openai-completions",
        "models": [
          {
            "id": "glm-5.1",
            "name": "GLM-5.1",
            "reasoning": true,
            "input": ["text"]
          },
          {
            "id": "glm-5-turbo",
            "name": "GLM-5-Turbo",
            "reasoning": true,
            "input": ["text"],
            "cost": {
              "input": 0,
              "output": 0,
              "cacheRead": 0,
              "cacheWrite": 0
            }
          }
        ]
      }
    }
  }
}
```

Important fields:

- `baseUrl` points to the local LiteLLM service
- `apiKey` should match the `master_key` configured in `litellm_config.yaml`
- `models` lists the model ids you want OpenClaw to see

### 2. Register aliases under `agents.defaults.models`

Example:

```json
{
  "agents": {
    "defaults": {
      "model": {
        "primary": "openai/gpt-5"
      },
      "models": {
        "litellm/glm-5.1": {
          "alias": "glm-5.1"
        },
        "litellm/glm-5-turbo": {
          "alias": "glm-5-turbo"
        },
        "openai/gpt-5": {
          "alias": "gpt-5"
        }
      }
    }
  }
}
```

If you want `batch_openclaw.py` or `batch_filegen.py` to use LiteLLM, the corresponding `.env` values should also use the LiteLLM-prefixed model ids:

```bash
OPENCLAW_MODEL=litellm/glm-5-turbo
GEN_OPENCLAW_MODEL=litellm/glm-5-turbo
```

Make sure these values match the models you registered in `.openclaw/openclaw.json`.

## How to Verify the Setup

After configuration, a good validation sequence is:

1. Start the LiteLLM gateway.
2. Restart OpenClaw.
3. Open the OpenClaw TUI.
4. Run `/models` and confirm that `litellm/glm-5.1` and `litellm/glm-5-turbo` are visible.
5. Switch to one of the LiteLLM models and run a normal conversation.

If everything is configured correctly, you should usually observe:

- OpenClaw responds normally
- `litellm_config/litellm.log` contains lines such as:

```bash
"POST /v1/chat/completions HTTP/1.1" 200 OK
```

- `litellm_config/success_events_all.jsonl` appears or keeps growing

## Recommendation

If you plan to capture traces with LiteLLM long term, it is worth standardizing both:

- `OPENCLAW_MODEL`
- `GEN_OPENCLAW_MODEL`

on `litellm/...` model ids, so both reverse file generation and forward trajectory generation are captured uniformly at the proxy layer.

## Post-processing

`success_events_all.jsonl` is the raw LiteLLM capture. It is comprehensive, but not very convenient to inspect directly.

To convert it into a more readable conversation-oriented format, run:

```bash
uv run python src/process_data/process_conversations.py \
  --input_file ./litellm_config/success_events_all.jsonl \
  --output_file ./litellm_config/message.jsonl
```

That derived file is better for direct inspection, sampling, and downstream processing.
