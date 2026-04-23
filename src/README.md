
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

```bash
PYTHONUNBUFFERED=1 nohup python src/batch_openclaw.py run \
  --workspace-hub /path/to/workspace_hub \
  --workspace-base /path/to/workspace_save \
  --results-dir /path/to/result \
  --skills-pool /path/to/skills-selected \
  --max-domain-parallel 20 > ./result/syn_data_test/filegen_log.txt 
```
可以通过`SKILLS_TO_REMOVE`参数来控制不使用的技能，`REQUIRED_SKILLS`参数来控制必须使用的技能。
`REQUIRED_SKILLS`参数和`--skills-pool`配合使用，`--skills-pool`为skill池地址，`REQUIRED_SKILLS`为必须提供给openclaw的skill。
```python
SKILLS_TO_REMOVE: set[str] = {"synthetic-test-files"}
REQUIRED_SKILLS: set[str] = {

}
# 通过填入指定skill的名字，可以控制必须提供给openclaw的skill
# REQUIRED_SKILLS: set[str] = {
#   "search", "ocr"
# }
```