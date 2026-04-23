## Openclaw文件合成
`src/batch_filegen.py` 用来为 `gen_query` 阶段产出的 query 反向合成所需输入文件。它会先判断每条 query 是否真的需要预先存在的本地文件，再调用 OpenClaw 和 `claw-input-file-generator` 相关 skill 去生成这些文件。

脚本支持 4 个子命令：

- `run`：执行输入文件合成任务
- `status`：查看当前进度
- `reset`：清空日志，下次从头开始跑
- `cleanup`：清理残留的 OpenClaw agents

最常用的是 `run`：

```bash
PYTHONUNBUFFERED=1 nohup python src/batch_filegen.py run \
  --workspace-hub /path/to/gen_query_workspace_hub \
  --workspace-base /path/to/filegen_workspace_base \
  --results-dir /path/to/filegen_result \
  --skills-source /path/to/generator_skills \
  --max-domain-parallel 5 \
  > /path/to/filegen_run.log 2>&1 &
```
建议尽量传绝对路径，避免 OpenClaw 在后台运行时找错目录。

### 输入目录约定

`--workspace-hub` 是 `gen_query` 阶段产出的 workspace 根目录。脚本会遍历它下面所有包含 `queries_persona.jsonl` 的子目录，并把这些子目录当作待处理 workspace。

一个典型目录结构如下：

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

其中：

- `workspace_hub`：上游 `gen_query` 阶段产生的原始 workspace
- `workspace_base`：给 OpenClaw 使用的临时 workspace 根目录；脚本会为每个 workspace 创建一个对应的目录，例如 `workspace_001_workspace`
- `filegen_result`：保存本轮 filegen 的对话轨迹和汇总结果

### 关键参数说明

- `--workspace-hub`：必填，输入数据目录
- `--workspace-base`：`run` 时必填，OpenClaw 使用的临时 workspace 根目录
- `--results-dir`：`run` 时必填，结果输出目录
- `--skills-source`：`run` 时必填，文件合成相关 skills 的来源目录
- `--openclaw-model`：OpenClaw 使用的模型；默认读取 `.env` 中的 `GEN_OPENCLAW_MODEL`
- `--openclaw-timeout`：单条任务超时时间，默认 `1200` 秒
- `--max-domain-parallel`：workspace 之间的并发数，默认 `5`
- `--filter-timeout`：预筛选模型超时时间，默认 `50` 秒
- `--filter-workers`：预筛选并发数，默认 `1`
- `--env-file`：环境变量文件路径，默认 `.env`

`--skills-source` 一般指向解压后的 `generator_skills` 目录。脚本会先把原始 workspace 中的 `skills/` 复制到临时 workspace，再把 `--skills-source` 中的 skill 同步到临时 workspace 的 `skills/` 下，供 OpenClaw 在生成输入文件时调用。如果两边有同名 skill，`--skills-source` 中的版本会覆盖临时 workspace 中已有的版本。

### 运行前准备

先确保 OpenClaw 已经可用，并确认模型可正常调用：

```bash
openclaw models list
```

`.env` 中至少需要配置两类模型：

```bash
# OpenClaw 用于生成输入文件
GEN_OPENCLAW_MODEL=ali-qwen/qwen3.6-plus

# 预筛选模型：判断 query 是否需要预先存在的输入文件
FILTER_MODEL=qwen3.6-plus
FILTER_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
FILTER_API_KEY=your_api_key_here
```

如果缺少 `GEN_OPENCLAW_MODEL`、`FILTER_MODEL`、`FILTER_API_BASE` 或 `FILTER_API_KEY`，脚本在 `run` 模式启动前就会直接报错。

### 运行逻辑

这个脚本的执行流程大致如下：

- 读取每个 workspace 下的 `queries_persona.jsonl`
- 先用 `FILTER_MODEL` 预筛选哪些 query 真的需要输入文件
- 对不需要输入文件的记录记为 `skip`
- 对需要生成的记录，先把原始 workspace 内容同步到 `workspace_base/<ws_name>_workspace`
- 同步时会保留原始 workspace 的 `skills/`，并额外加入 `--skills-source` 中的文件生成 skill
- 再调用 OpenClaw，让 `claw-input-file-generator` 等 skill 生成 query 所需输入文件

并发方式上：

- workspace 之间并发执行
- 单个 workspace 内部串行执行
- 每条任务开始前都会创建一个干净 agent，任务结束后立即清理

### 输出内容

这个阶段的输出分成两部分：

`workspace_hub/<workspace_name>/` 下：

- `filegen_log.jsonl`：逐条记录 filegen 的执行结果
- 状态可能包括 `success`、`skip`、`failed`、`timeout`、`error`、`empty_payloads`

`results-dir/` 下：

- `summary.json`：本次运行的汇总统计
- `<workspace>/`：每个 workspace 对应一个结果目录
- `<workspace>/<session_id>_*.jsonl`：从 OpenClaw session 中拷贝出的对话轨迹

其中：

- `success`：成功生成了输入文件
- `skip`：预筛选判断该 query 不需要输入文件
- `empty_payloads`：OpenClaw 调用了但没有真正生成出文件

### 其他子命令

查看当前进度：

```bash
python src/batch_filegen.py status \
  --workspace-hub /path/to/workspace_hub
```

清空 `filegen_log.jsonl`，下次从头开始跑：

```bash
python src/batch_filegen.py reset \
  --workspace-hub /path/to/workspace_hub
```

清理残留 agents：

```bash
python src/batch_filegen.py cleanup \
  --workspace-hub /path/to/workspace_hub
```

虽然 `cleanup` / `reset` / `status` 也复用了同一套参数接口，但最关键的是 `--workspace-hub` 要和当前这批数据对应。


## Openclaw轨迹生成
`src/batch_openclaw.py` 用来把 `workspace_hub` 中已经准备好的 query 批量交给 OpenClaw，生成对话轨迹，并支持按 domain 并发、断点续跑、技能池随机采样。

如果你希望获取到底层模型最原始的请求和返回结果，而不只是 OpenClaw 默认导出的 session 轨迹文件，那么必须启用项目中的 `litellm_config/`，让 OpenClaw 通过 LiteLLM 网关调用模型。否则默认流程只能拿到 session 轨迹，拿不到最底层的原始请求数据。详细说明见根目录下的 [litellm_config/README.md](/mnt/d/project/clawsynth/litellm_config/README.md)。

脚本支持 4 个子命令：

- `run`：执行所有轨迹生成任务
- `status`：查看当前 checkpoint 进度
- `reset`：清空 checkpoint，下次从头跑
- `cleanup`：清理残留的 OpenClaw agents

最常用的是 `run`：

```bash
PYTHONUNBUFFERED=1 nohup python src/batch_openclaw.py run \
  --workspace-hub /path/to/workspace_hub \
  --workspace-base /path/to/workspace_base \
  --results-dir /path/to/openclaw_result \
  --skills-pool /path/to/skills-selected \
  --max-domain-parallel 20 \
  > /path/to/openclaw_run.log 2>&1 &
```

建议尽量传绝对路径，避免 OpenClaw 在多进程或后台运行时找错目录。

### 输入目录约定

`--workspace-hub` 是输入数据根目录。脚本会遍历它下面的每个 domain 子目录，并读取其中的 `queries_persona.jsonl`。每一行如果包含 `result` 字段，就会把该字段内容作为一条 OpenClaw 任务消息。

一个典型的目录结构如下：

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

其中：

- `workspace_hub`：上游生成好的 query、skills 和反向合成文件等原始数据；通常传入上一节 `Openclaw文件合成` 的 `--workspace-base` 路径，因为输入文件会被生成到该临时 workspace 中
- `workspace_base`：OpenClaw 运行时使用的工作区根目录；脚本会为每个 domain 创建独立 workspace，例如 `domain_a_workspace`
- `openclaw_result`：保存轨迹结果、checkpoint 和汇总信息

### 关键参数说明

- `--workspace-hub`：必填，原始数据目录
- `--workspace-base`：`run` 时必填，OpenClaw 工作区根目录
- `--results-dir`：`run` 时必填，结果输出目录
- `--openclaw-model`：OpenClaw 使用的模型；默认读取 `.env` 中的 `OPENCLAW_MODEL`
- `--openclaw-timeout`：单条任务超时时间，默认 `1200` 秒
- `--max-domain-parallel`：domain 之间的并发数，默认 `5`
- `--skills-pool`：可选，额外 skill 池目录
- `--skill-min`：每次随机抽取 skill 的最小数量，默认 `3`
- `--skill-max`：每次随机抽取 skill 的最大数量，默认 `3`
- `--env-file`：环境变量文件路径，默认 `.env`


### 运行逻辑

脚本的执行方式有几个比较重要的设计点：

- 每个 domain 使用一个独立 workspace，互不干扰
- domain 之间并发执行，但单个 domain 内部按任务串行执行
- 每跑一条任务，都会先删除旧 agent，再新建一个干净 agent，保证上下文隔离
- 每条任务执行后会把结果追加写入 `checkpoint.jsonl`，所以下次可以自动跳过已完成任务

换句话说，如果中途中断，再次执行同样的 `run` 命令时，脚本会从上次未完成的位置继续跑。

### 输出内容

`--results-dir` 下通常会生成这些内容：

- `checkpoint.jsonl`：逐条任务的执行记录，`success` / `failed` / `timeout` / `error` 都会记下来
- `summary.json`：本次运行的汇总统计，包括成功数、失败数、是否从 checkpoint 恢复等
- `<domain>/`：每个 domain 对应一个结果目录
- `<domain>/<session_id>_*.jsonl`：从 OpenClaw session 中拷贝出的对话轨迹文件

例如一条任务的 session id 形如 `domain_a_task_003`。

### Skill 池说明

如果传了 `--skills-pool`，脚本会在每个 domain 的 workspace 下：

- 先移除 `SKILLS_TO_REMOVE` 中列出的 skill
- 再从 `skills-pool` 中随机采样 skill，并通过软链接挂到 workspace 的 `skills/` 目录
- 如果配置了 `REQUIRED_SKILLS`，这些 skill 会被强制加入，不参与随机淘汰

当前脚本中的默认配置是：

```python
SKILLS_TO_REMOVE: set[str] = {"synthetic-test-files"}
REQUIRED_SKILLS: set[str] = {
}
```

如果你想稳定给 OpenClaw 提供某些通用能力，可以直接在 `src/batch_openclaw.py` 中修改 `REQUIRED_SKILLS`，例如：

```python
REQUIRED_SKILLS: set[str] = {
    "search",
    "ocr",
}
```

比较适合作为必选 skill 的通常是网页搜索、OCR、语音转文字这类基础能力。

### 其他子命令

查看当前进度：

```bash
python src/batch_openclaw.py status \
  --workspace-hub /path/to/workspace_hub \
  --workspace-base /path/to/workspace_base \
  --results-dir /path/to/openclaw_result
```

清空 checkpoint，从头开始跑：

```bash
python src/batch_openclaw.py reset \
  --workspace-hub /path/to/workspace_hub \
  --workspace-base /path/to/workspace_base \
  --results-dir /path/to/openclaw_result
```

清理残留 agents：

```bash
python src/batch_openclaw.py cleanup \
  --workspace-hub /path/to/workspace_hub \
  --workspace-base /path/to/workspace_base \
  --results-dir /path/to/openclaw_result
```

虽然 `cleanup` / `reset` / `status` 也复用了相同参数接口，但最关键的是 `--workspace-hub` 要和本次批处理数据对应，否则脚本无法正确识别 domain 集合。
