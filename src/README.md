
```bash
PYTHONUNBUFFERED=1 nohup python src/batch_filegen.py run \
    --workspace-hub ./result/syn_data_test/workspace_hub_test \
    --workspace-base ./result/syn_data_test/workspace_hub_test_filegen \
    --results-dir ./result/syn_data_test/filegen_result \
    --skills-source ./generator_skills  > ./result/syn_data_test/filegen_log.txt 2>&1 &
```
注：提供绝对路径最佳，确保openclaw能够找到正确的路径。


先确保 .env 已经配置：
```bash
# OpenClaw 执行模型（batch_openclaw 使用）
OPENCLAW_MODEL=litellm/glm-5-turbo

# OpenClaw 主模型
# openclaw model generate files
GEN_OPENCLAW_MODEL=ali-qwen/qwen3.6-plus

# 预筛选模型（batch_filegen_v2 使用）
FILTER_MODEL=qwen3.6-plus
FILTER_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
FILTER_API_KEY=your_api_key_here

# 生成 query 模型（gen_query 使用）
GEN_QUERY_MODEL=glm-5.1
GEN_QUERY_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
GEN_QUERY_API_KEY=your_api_key_here

```


## Openclaw轨迹生成
`src/batch_openclaw.py` 用来把 `workspace_hub` 中已经准备好的 query 批量交给 OpenClaw，生成对话轨迹，并支持按 domain 并发、断点续跑、技能池随机采样。

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

- `workspace_hub`：上游生成好的 query、反向合成文件等原始数据
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

可用模型可以先通过下面命令查看：

```bash
openclaw models list
```

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
