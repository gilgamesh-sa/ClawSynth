## LiteLLM 网关抓取

这个目录用于通过 LiteLLM 代理转接大模型接口，并把 OpenClaw 调用模型时的原始请求与返回结果记录下来。

直接通过 OpenClaw 本身通常拿不到完整的底层对话数据，而通过 LiteLLM 代理后，我们可以在代理层抓取：

- 发给模型的 `system` / `messages`
- 使用到的 `tools`
- 模型原始返回 `response_obj`
- 请求元信息和耗时

最终这些数据会被写入 `success_events_all.jsonl`，用于后续分析和数据回放。

## 目录说明

- `litellm_config.yaml.example`
  LiteLLM 代理配置模板。
- `litellm_config.yaml`
  你本地实际使用的 LiteLLM 配置文件。
- `custom_callbacks.py`
  自定义回调逻辑。当前会把成功请求写入 JSONL 文件。
- `success_events_all.jsonl`
  LiteLLM 成功请求日志，记录原始请求和响应。
- `litellm.log`
  LiteLLM 服务启动日志。

## 在 uv 环境中安装 LiteLLM

本项目推荐统一使用 `uv` 环境。由于这个目录下的回调脚本依赖：

- `litellm`
- `aiofiles`

建议在项目根目录执行：

```bash
uv add litellm aiofiles
```

如果你只是想同步项目中已经声明好的依赖，也可以执行：

```bash
uv sync
```

安装完成后，可以先确认 LiteLLM 是否已经在当前 uv 环境中可用：

```bash
uv run litellm --help
```

如果这条命令能正常输出帮助信息，说明 LiteLLM 已经成功加入本地 uv 环境。

## 配置 LiteLLM

先从模板复制出本地配置文件：

```bash
cp litellm_config/litellm_config.yaml.example litellm_config/litellm_config.yaml
```

然后编辑 `litellm_config/litellm_config.yaml`，至少要配置下面几项：

- `model_list`
  你希望代理暴露给 OpenClaw 的模型列表。
- `api_key`
  上游模型服务的真实 API Key。
- `api_base`
  上游模型服务地址。
- `master_key`
  LiteLLM 代理自身的访问密钥。

当前模板示例：

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

需要重点注意：

- `callbacks` 当前写的是 `custom_callbacks.proxy_handler_instance`
- 因此建议在 `litellm_config/` 目录下启动 LiteLLM，确保这个模块能被正确导入
- `master_key` 要和 OpenClaw 里的 `apiKey` 保持一致

## 启动 LiteLLM 网关

推荐在项目根目录执行下面命令：

```bash
cd litellm_config
nohup ../.venv/bin/litellm --config litellm_config.yaml --port 2013 > litellm.log 2>&1 &
cd ..
```

如果你不想依赖 `.venv` 的固定路径，也可以直接用 `uv run`：

```bash
cd litellm_config
nohup uv run litellm --config litellm_config.yaml --port 2013 > litellm.log 2>&1 &
cd ..
```

启动后可以通过日志确认服务是否正常：

```bash
tail -f litellm_config/litellm.log
```

看到类似输出通常说明启动成功：

```bash
Uvicorn running on http://0.0.0.0:2013
POST /v1/chat/completions HTTP/1.1" 200 OK
```

## 配置 OpenClaw 使用 LiteLLM 模型

接下来需要让 OpenClaw 不再直接调用上游模型，而是改为调用本地 LiteLLM 网关。

需要修改 OpenClaw 根目录下 `.openclaw/openclaw.json` 中的两部分。

### 1. 在 `models.providers` 中注册 LiteLLM Provider

示例：

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

这里的关键配置是：

- `baseUrl` 指向本地 LiteLLM 服务地址
- `apiKey` 使用 `litellm_config.yaml` 中配置的 `master_key`
- `models` 中列出你希望 OpenClaw 能看到的模型

### 2. 在 `agents.defaults.models` 中注册别名

示例：

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

如果你打算让 `batch_openclaw.py` 或 `batch_filegen.py` 走 LiteLLM，那么对应的 `.env` 模型名也应该改成：

```bash
OPENCLAW_MODEL=litellm/glm-5-turbo
GEN_OPENCLAW_MODEL=litellm/glm-5-turbo
```

当然，具体值要和你在 `.openclaw/openclaw.json` 里注册的模型保持一致。

## 如何验证是否配置成功

完成配置后，建议按下面顺序检查：

1. 启动 LiteLLM 网关
2. 重启 OpenClaw
3. 打开 OpenClaw TUI
4. 使用 `/models` 查看是否能看到 `litellm/glm-5.1`、`litellm/glm-5-turbo`
5. 切换到其中一个 LiteLLM 模型并发起一次正常对话

如果配置正确，通常会看到下面这些现象：

- OpenClaw 能正常回复
- `litellm_config/litellm.log` 中出现：

```bash
"POST /v1/chat/completions HTTP/1.1" 200 OK
```

- `litellm_config/` 目录下出现或持续追加：

```bash
success_events_all.jsonl
```



## 建议

如果你后续会长期用 LiteLLM 抓轨迹，建议把：

- `OPENCLAW_MODEL`
- `GEN_OPENCLAW_MODEL`

都统一切到 `litellm/...` 前缀模型，这样 query 文件合成和正向轨迹生成两个阶段都可以统一从代理层抓到底层请求和返回结果。
