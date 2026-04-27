`soft_verify` 的环境变量现在统一放在项目根目录的 `.env` / `.env.example` 中，不再单独维护 `src/soft_verify/.env`。
`soft_verify` 依赖也已经并入主项目的 `pyproject.toml`，在仓库根目录执行 `uv sync` 后，可以直接用主环境运行这里的脚本。

step1
```bash
python step1_plan.py --input tasks.jsonl --output plan.jsonl --workers 8
```
step2
```bash
python step2_evaluate.py --input plan.jsonl --output result.jsonl --workers 8
```

PADDLEOCR_AISTUDIO_ACCESS_TOKEN可以通过访问：`https://ai.baidu.com/ai-doc/AISTUDIO/Cmkz2m0ma`获取
