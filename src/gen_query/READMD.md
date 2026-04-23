# Synthesizer Query Normal

## 项目结构

- `../src/gen_query/step0_generate_random_workspaces.py`
  根据 `config.py` 里的 skill hub 配置，生成 `workspace_hub`。
- `../src/gen_query/step1_generate_queries.py`
  直接读取已有 `workspace_hub` 中每个 `workspace_*/skills/`，并在对应 workspace 下生成 prompt。
- `../src/gen_query/step2_run_benchmark.py`
  调用你配置的 OpenAI 兼容接口，把 prompt 生成 query，继续写回原 workspace。
- `../src/gen_query/step3_persona_rewrite.py`
  对 query 做 persona 改写，输出最终结果，继续写回原 workspace。
- `../src/gen_query/config.py`
  `step0-step3` 的唯一配置入口。当前不再读取 `.env`。
- `../src/gen_query/utils/`
  `step0-step3` 共享的工具模块，如 workspace 扫描、JSONL 读写和 LLM 调用。
- `../src/gen_query/data/unique_task_instructions.json`
  step3 用到的人设池。

## 目录约定

- `WORKSPACE_HUB`
  step0 生成出来、并由 step1-step3 继续写回的 workspace 池。里面应该是很多 `${WS_PREFIX}*` 目录，每个目录下有 `skills/`。

期望输入结构示例：

```text
workspace_hub_0409/
  workspace_001/
    skills/
      some-skill/
        SKILL.md
      another-skill/
        SKILL.md
```

## 首次使用

1. 修改 `src/gen_query/config.py`。
2. 设置你的 `SKILL_HUBS`、`WORKSPACE_HUB`、`WS_PREFIX`、step0 采样参数、模型地址和 persona 文件路径。
3. 安装依赖并执行 step0 到 step3。

<!-- ```bash
cd /mnt/d/project/ClawSynth
python3 -m pip install tqdm
python3 -m src.gen_query.step0_generate_random_workspaces
python3 -m src.gen_query.step1_generate_queries
python3 -m src.gen_query.step2_run_benchmark
python3 -m src.gen_query.step3_persona_rewrite
```

也可以直接顺序执行：

```bash
cd /mnt/d/project/ClawSynth
bash src/gen_query/run_step1_to_step3.sh
```

或者直接使用新名字更清晰的脚本： -->

```bash
cd /mnt/d/project/ClawSynth
bash src/gen_query/run_step0_to_step3.sh
```

如果想临时覆盖 `config.py` 里的 skill hub 或 workspace hub：

```bash
cd /mnt/d/project/ClawSynth
bash src/gen_query/run_step0_to_step3.sh   --skill-hub skills   --skill-hub /path/to/other_skills   --workspace-hub /path/to/workspace_hub_test
```

## 运行前必须确认

- `SKILL_HUBS` 指向有效的 skill hub 目录。
- `WORKSPACES_TO_BUILD`、`MIN_SKILLS_PER_WORKSPACE`、`MAX_SKILLS_PER_WORKSPACE` 已按你的期望设置。
- `LITELLM_API_BASE`、`LITELLM_API_KEY`、`LITELLM_MODEL` 已换成你自己的配置。
- `INSTRUCTIONS_FILE` 指向有效的人设 JSON 文件。
- `step0` 执行后，`WORKSPACE_HUB` 下的目录结构是 `${WS_PREFIX}*/skills/<skill>/SKILL.md`。

## 输出文件

- step0: `${WORKSPACE_HUB}/${WS_PREFIX}*`
- step1: `<workspace>/tmp_benchmark_queries.jsonl`
- step2: `<workspace>/queries.jsonl`
- step3: `<workspace>/queries_persona.jsonl`

最终可交付结果就在 `WORKSPACE_HUB` 里各 workspace 下的 `queries_persona.jsonl`。

## 注意

- 本项目默认运行 step0 到 step3。
- `agents/` 和旧的 `references/` 参考文件已经删除，只保留运行所需内容。

PYTHONUNBUFFERED=1 nohup python batch_openclaw_v3.py run > output.log 2>&1 &
