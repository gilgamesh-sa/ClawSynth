[![English](https://img.shields.io/badge/Language-English-blue)](./README.md)
[![简体中文](https://img.shields.io/badge/语言-简体中文-red)](./README.zh-CN.md)

# Synthesizer Query Generation

这个目录对应项目中的一个子阶段：根据 skill 组合生成 query，并进一步做人设改写，最终产出可用于后续 OpenClaw 轨迹生成的 `queries_persona.jsonl`。

## 整体流程

整个流程分为 4 个 step：

- `step0_generate_random_workspaces.py`
  从一个或多个 skill hub 中随机采样 skill，生成一批 workspace。
- `step1_generate_queries.py`
  读取每个 workspace 下的 `skills/`，为每个 skill 生成 query prompt，输出 `tmp_benchmark_queries.jsonl`。
- `step2_run_benchmark.py`
  调用 OpenAI 兼容接口，根据 step1 生成的 prompt 产出原始 query，输出 `queries.jsonl`。
- `step3_persona_rewrite.py`
  对 step2 的 query 做 persona 改写，输出最终结果 `queries_persona.jsonl`。

最终可交付结果是每个 workspace 下的 `queries_persona.jsonl`。

## 项目结构

- `src/gen_query/config.py`
  `step0-step3` 的主配置入口。
- `src/gen_query/run_step0_to_step3.sh`
  一键串行执行 step0 到 step3 的脚本。
- `src/gen_query/utils/`
  公共工具模块，包括 workspace 扫描、JSONL 读写和 LLM 调用。
- `src/gen_query/data/unique_task_instructions.json`
  step3 使用的人设池。

## 输入输出目录约定

`WORKSPACE_HUB` 是这个子流程的核心工作目录。step0 会在这里创建 workspace，step1-step3 会继续把中间结果和最终结果写回这些 workspace。

目录示例：

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

这里有两个命名规则需要注意：

- `WORKSPACE_HUB` 是 workspace 根目录，例如 `result/syn_data_test_v2/workspace_test`
- 每个 workspace 的目录名是 `${WS_PREFIX}001`、`${WS_PREFIX}002` 这种形式，而不是固定的 `workspace_001`

## 配置方式

主要配置在 `src/gen_query/config.py`，但模型相关配置不是直接写死在文件里，而是优先从项目根目录 `.env` 中读取：

```bash
GEN_QUERY_MODEL=glm-5.1
GEN_QUERY_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
GEN_QUERY_API_KEY=your_api_key_here
```

也就是说：

- 路径、采样规模、人设文件等，主要在 `config.py` 中配置
- 模型名、API Base、API Key，推荐放在项目根目录 `.env`

## 核心配置项

### Step 0: workspace generation

- `SKILL_HUBS`
  skill hub 列表。step0 会扫描这些目录下直接包含 `SKILL.md` 的子目录。
- `WORKSPACE_HUB`
  workspace 根目录。
- `WS_PREFIX`
  workspace 目录名前缀。
- `WORKSPACES_TO_BUILD`
  生成多少个 workspace。
- `MIN_SKILLS_PER_WORKSPACE`
  每个 workspace 最少采样多少个 skill。
- `MAX_SKILLS_PER_WORKSPACE`
  每个 workspace 最多采样多少个 skill。
- `WORKSPACE_COPY_MODE`
  workspace 中 skill 的放置方式，支持 `symlink` 或 `copy`。
- `WORKSPACE_FORCE_CLEAN`
  是否在 step0 开始前清空输出目录。
- `RANDOM_SEED`
  控制采样和部分 prompt 随机性的随机种子。

### Step 1: prompt generation

- `QUERIES_PER_SKILL`
  每个 skill 生成多少条 query prompt。

step1 生成的是 prompt 记录，不是最终 query。输出文件是 `tmp_benchmark_queries.jsonl`。

### Step 2/3: LLM generation and persona rewrite

- `LITELLM_MODEL`
  query 生成和 persona 改写使用的模型名，从 `.env` 读取。
- `LITELLM_API_BASE`
  模型服务地址，从 `.env` 读取。
- `LITELLM_API_KEY`
  模型服务密钥，从 `.env` 读取。
- `BENCH_CONCURRENCY`
  step2 生成原始 query 的并发数。
- `REWRITE_WORKERS`
  step3 persona 改写并发数。
- `REWRITE_TIMEOUT`
  step3 单条改写超时时间。
- `INSTRUCTIONS_FILE`
  persona 指令池文件。

## 推荐运行方式

最简单的方式是直接运行：

```bash
bash src/gen_query/run_step0_to_step3.sh
```

如果你不想改脚本里的默认路径，也可以直接在命令行覆盖：

```bash
bash src/gen_query/run_step0_to_step3.sh \
  --skill-hub /path/to/skills \
  --workspace-hub /path/to/workspace_hub
```

其中：

- `--skill-hub` 可以传多次，用来追加 skill hub
- `--workspace-hub` 会覆盖 step0-step3 使用的 workspace 根目录

如果你希望完全分步执行，也可以单独跑每个 step：

```bash
python3 -m src.gen_query.step0_generate_random_workspaces --output /path/to/workspace_hub
python3 -m src.gen_query.step1_generate_queries --workspace-hub /path/to/workspace_hub
python3 -m src.gen_query.step2_run_benchmark --workspace-hub /path/to/workspace_hub
python3 -m src.gen_query.step3_persona_rewrite --workspace-hub /path/to/workspace_hub
```

## 运行前检查

运行前建议确认下面这些项：

- `SKILL_HUBS` 或 `--skill-hub` 指向有效目录，且子目录中包含 `SKILL.md`
- `WORKSPACE_HUB` 或 `--workspace-hub` 指向你期望的输出目录
- `WORKSPACES_TO_BUILD`、`MIN_SKILLS_PER_WORKSPACE`、`MAX_SKILLS_PER_WORKSPACE` 已按实验规模设置好
- 项目根目录 `.env` 中已经配置 `GEN_QUERY_MODEL`、`GEN_QUERY_API_BASE`、`GEN_QUERY_API_KEY`
- `INSTRUCTIONS_FILE` 指向有效的人设 JSON 文件

## 各阶段输出

- step0
  生成 `${WORKSPACE_HUB}/${WS_PREFIX}001` 这类 workspace 目录，并在其中创建 `skills/`
- step1
  在每个 workspace 下生成 `tmp_benchmark_queries.jsonl`
- step2
  在每个 workspace 下生成 `queries.jsonl`
- step3
  在每个 workspace 下生成 `queries_persona.jsonl`

## 结果文件说明

### `tmp_benchmark_queries.jsonl`

这是 step1 生成的 prompt 数据，供 step2 调模型使用。通常会包含：

- `id`
- `workspace`
- `skills`
- `skill_main`
- `type`
- `input_style`
- `query`

这里的 `query` 还不是最终用户 query，而是发给模型的完整 prompt。

### `queries.jsonl`

这是 step2 生成的原始 query 结果。在你当前的实际产物中，一条记录大致长这样：

```json
{
  "id": "workspace_test001__weather-1.0.0_01",
  "workspace": "workspace_test001",
  "skills": ["weather-1.0.0"],
  "skill_main": "weather-1.0.0",
  "type": "file",
  "input_style": "explicit",
  "query": "...模型输入 prompt ...",
  "result": "帮我查一下西宁接下来三天的天气情况，然后根据查到的日照和气象数据，写一篇关于光伏产业近期发电量影响分析的短文，保存到 `./photovoltaic_weather_analysis_83241.md`"
}
```

其中真正可用于后续阶段的原始 query 在 `result` 字段里。

### `queries_persona.jsonl`

这是 step3 生成的最终结果文件。它会保留原始记录，并在此基础上增加 persona 改写后的信息。例如：

```json
{
  "id": "workspace_test001__weather-1.0.0_01",
  "workspace": "workspace_test001",
  "skills": ["weather-1.0.0"],
  "result": "您好！我最近手头实在太忙啦，麻烦您抽空帮我处理一下好吗？...",
  "result_original": "帮我查一下西宁接下来三天的天气情况，然后根据查到的日照和气象数据...",
  "persona": "You are polite, optimistic, busy."
}
```

可以把这个文件理解为最终交付物：

- `result` 是 persona 改写后的 query
- `result_original` 是 step2 的原始 query
- `persona` 是这条样本使用的人设

## 补充说明

- step0 默认会从 skill hub 中随机采样 skill 组合生成 workspace
- step1 会同时生成不同类型的 query prompt，例如 `file/chat` 和 `explicit/vague` 风格
- 如果你只关心最终可交付数据，优先看各 workspace 下的 `queries_persona.jsonl`
