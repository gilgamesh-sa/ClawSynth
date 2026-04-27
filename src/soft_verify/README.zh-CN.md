[![English](https://img.shields.io/badge/Language-English-blue)](./README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red)](./README.zh-CN.md)

# soft_verify

`soft_verify` 是 ClawSynth 中用于验证 OpenClaw 对话轨迹质量的模块。它的目标不是检查模型是否严格按固定模板输出，而是结合：

- 用户 query
- 对应 workspace 中的文件状态
- agent 最终回复

生成一组可执行的验证检查项，再由一个带工具调用能力的验证 agent 对这些检查项进行打分，最终输出 `pass`、`review` 或 `fail`。

当前实现偏向宽松验证，适合大规模数据清洗、抽样检查和初步过滤。如果你需要更严格的判定标准，可以继续收紧提示词、打分阈值或工具逻辑。

## 验证流程概览

完整链路分成 4 步：

1. 通过 LiteLLM 网关抓取 OpenClaw 正向轨迹生成阶段的原始日志
2. 把原始日志整理成更易处理的对话格式
3. 抽取 `intent`、`workspace`、`agent_final_output`，构造成统一验证输入
4. 执行 `step1_plan.py` 和 `step2_evaluate.py`，得到最终验证结果

推荐流程如下：

```text
OpenClaw 正向轨迹生成
  -> LiteLLM success_events_all.jsonl
  -> process_conversations.py 生成 message.jsonl
  -> extract_for_check.py 生成 tasks.jsonl
  -> step1_plan.py 生成 plan.jsonl
  -> step2_evaluate.py 生成 result.jsonl
```

## 运行前准备

### 1. 主项目环境

`soft_verify` 的依赖已经并入主项目的 `pyproject.toml`。在仓库根目录执行：

```bash
uv sync
```

后续命令都建议从仓库根目录运行，并统一使用主项目的 `uv` 环境。

### 2. 环境变量

至少需要配置：

```bash
# 验证模型
VERIFY_API_KEY=your_api_key_here
VERIFY_MODEL=glm-5
# VERIFY_API_BASE=https://open.bigmodel.cn/api/paas/v4
VERIFY_TIMEOUT_SECONDS=120
VERIFY_SOFT_AGENT_MAX_ROUNDS=20

# OCR 能力
PADDLEOCR_AISTUDIO_ACCESS_TOKEN=your_paddleocr_aistudio_access_token
```

其中：

- `VERIFY_*`：用于生成验证计划和执行 soft-check agent
- `PADDLEOCR_AISTUDIO_ACCESS_TOKEN`：用于验证过程中读取图片或 PDF 中的文本内容

`PADDLEOCR_AISTUDIO_ACCESS_TOKEN` 可以参考百度 AI Studio 文档获取：`https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma`

### 3. LiteLLM 网关原始日志

如果你没有启用 LiteLLM 网关抓取到底层模型的原始请求与返回结果，就无法使用这里这套验证流程。

详细配置方式见仓库根目录下的 [../../litellm_config/README.zh-CN.md](../../litellm_config/README.zh-CN.md)。

验证流程依赖的原始日志文件是：

```text
litellm_config/success_events_all.jsonl
```

这个文件保存的是 LiteLLM 抓到的原始调用日志。

## 输入数据准备

### 第一步：整理 LiteLLM 原始轨迹

先把 `success_events_all.jsonl` 整理成更易读、更稳定的对话格式：

```bash
uv run python src/process_data/process_conversations.py \
  --input_file ./litellm_config/success_events_all.jsonl \
  --output_file ./litellm_config/message.jsonl
```

输出文件：

```text
litellm_config/message.jsonl
```

### 第二步：转换为 soft_verify 统一输入格式

然后把对话轨迹转换成 `soft_verify` 使用的统一输入格式：

```bash
uv run python src/process_data/extract_for_check.py \
  --input_file ./litellm_config/message.jsonl \
  --workspace_hub_dir ./result/syn_data_test_v2/workspace_test \
  --workspace_base ./result/syn_data_test_v2/openclaw_workspace \
  --output_file ./result/syn_data_test_v2/tasks_for_check.jsonl
```

参数说明：

- `--input_file`：上一步 `process_conversations.py` 生成的 `message.jsonl`
- `--workspace_hub_dir`：上游 query 数据所在的 `workspace_hub`
- `--workspace_base`：正向轨迹生成阶段真正运行 OpenClaw 的 `workspace_base`
- `--output_file`：输出给 `soft_verify` 使用的 JSONL 文件

这里要特别注意：

- `--workspace_hub_dir` 和 `--workspace_base` 必须与实际那一轮 OpenClaw 正向轨迹生成使用的目录对应
- 如果路径对应错了，后面验证时拿到的 workspace 状态就会不准确

输出文件中的每条记录大致包含：

```json
{
  "intent": "用户 query 文本",
  "workspace": "/abs/path/to/workspace",
  "agent_final_output": "agent 最终回复"
}
```

## 执行验证

验证分成两个 step。

### Step 1：生成验证计划

`step1_plan.py` 会根据 `intent`、`workspace` 和 `agent_final_output` 生成一组 `llm_checks`，也就是后续验证 agent 要执行的检查项。

```bash
uv run python src/soft_verify/step1_plan.py \
  --input ./result/syn_data_test_v2/tasks_for_check.jsonl \
  --output ./result/syn_data_test_v2/step1_output.jsonl \
  --workers 8
```

常用参数：

- `--input`：上一步生成的统一输入 JSONL
- `--output`：验证计划输出文件
- `--workers`：并发 worker 数，默认 `8`
- `--path-mode`：路径解析模式，默认 `auto`

`--path-mode` 支持：

- `auto`
- `workspace-only`
- `absolute-priority`

一般保持默认的 `auto` 即可。

输出文件中的核心字段包括：

- `intent`
- `workspace`
- `agent_final_output`
- `llm_checks`

如果某条记录在 step1 失败，输出里也会保留失败记录，包含错误信息，方便后续排查。

### Step 2：执行验证打分

`step2_evaluate.py` 会读取 step1 生成的 `llm_checks`，调用带工具能力的验证 agent，对每条检查项执行验证并输出最终分数与结论。

```bash
uv run python src/soft_verify/step2_evaluate.py \
  --input ./result/syn_data_test_v2/step1_output.jsonl \
  --output ./result/syn_data_test_v2/step2_output.jsonl \
  --workers 8
```

常用参数：

- `--input`：`step1_plan.py` 的输出文件
- `--output`：最终验证结果输出文件
- `--workers`：并发 worker 数，默认 `8`
- `--path-mode`：路径解析模式，默认 `auto`

最终结果里通常会包含：

- `verdict`
- `score`
- `llm_check_results`

## 补充说明

- 这套流程依赖 LiteLLM 原始日志，因此建议在 OpenClaw 正向轨迹生成阶段就启用 LiteLLM。
- 如果你只拿到了 OpenClaw session 轨迹，而没有 `success_events_all.jsonl`，这套验证流程无法完整运行。
- 如果你希望从更宽松的验证逐步收紧标准，优先从 `step1_plan.py` 和 `step2_evaluate.py` 的提示词与阈值入手。
