#!/usr/bin/env python3
"""Step 1: generate prompt records for each workspace skill."""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from src.gen_query.config import QUERIES_PER_SKILL, RANDOM_SEED, WORKSPACE_HUB, WS_PREFIX
from src.gen_query.utils.constants import TMP_PROMPTS_FILENAME
from src.gen_query.utils.jsonl_io import write_jsonl
from src.gen_query.utils.workspace import SkillInfo, collect_workspace_specs


TYPE_WEIGHTS = {
    ("file", "explicit"): 3,
    ("file", "vague"): 1,
    ("chat", "explicit"): 1,
    ("chat", "vague"): 1,
}
TYPE_CHOICES = list(TYPE_WEIGHTS.keys())
TYPE_PROBS = list(TYPE_WEIGHTS.values())

OUTPUT_FORMATS = [
    ".html（HTML 网页）",
    ".xlsx（Excel 表格）",
    ".png（PNG 图片）",
    ".docx（Word 文档）",
    ".md（Markdown 文档）",
    ".mp3（MP3 音频）",
    ".pdf（PDF 文档）",
    ".csv（CSV 数据文件）",
    ".pptx（PowerPoint 演示文稿）",
    ".svg（SVG 矢量图）",
]

TOPICS = [
    "新能源汽车", "宠物经济", "咖啡连锁行业", "跨境电商", "智能家居",
    "老年护理", "电竞产业", "农业科技", "在线教育", "医美行业",
    "航天航空", "精酿啤酒", "二手奢侈品", "健身运动", "母婴用品",
    "古典音乐演出", "非遗手工艺", "露营户外", "剧本杀行业", "宠物医疗",
    "共享经济", "数字藏品NFT", "社区团购", "心理咨询", "中医药",
    "新式茶饮", "预制菜", "充电桩基建", "快递物流", "短剧影视",
    "植物基食品", "无人驾驶", "碳中和", "3D打印", "虚拟偶像",
    "少儿编程", "银发旅游", "潮玩盲盒", "宠物食品", "民宿经营",
    "量子计算", "脑机接口", "合成生物", "供应链金融", "数字人民币",
    "光伏产业", "海洋经济", "体育赛事", "音乐节演出", "汉服文化",
    "考研留学", "职业培训", "机器人产业", "生物医药", "芯片封测",
    "保险科技", "直播电商", "文创产品", "仓储物流", "智慧城市",
]

SCENARIOS = [
    "请生成一个偏向工作汇报场景的 query",
    "请生成一个偏向个人学习或研究场景的 query",
    "请生成一个偏向创意或设计场景的 query",
    "请生成一个偏向数据分析场景的 query",
    "请生成一个偏向自动化或效率提升场景的 query",
    "请生成一个偏向内容创作场景的 query",
    "请生成一个偏向决策支持场景的 query",
    "请生成一个偏向客户服务或沟通场景的 query",
    "请生成一个偏向教育培训场景的 query",
    "请生成一个比较独特或小众的使用场景的 query",
]

INPUT_SECTION_EXPLICIT = """
## ⚠️ 【最重要】输入文件路径 — 绝对不能遗漏！
很多 skill 需要用户提供本地文件才能工作。如果你使用了这类 skill（无论是主 skill 还是组合 skill），**query 中必须明确写出每一个输入文件的完整路径**，一个都不能遗漏！

**规则**：
- 文件路径必须带子目录前缀 `./`，文件名用英文且贴合场景
- 每个需要输入文件的 skill 对应的文件路径都必须出现在 query 中
- query 中要自然地引用这些文件（如"帮我识别 `./receipt_photo.png` 这张图片"、"我有一份文件 `./project_plan.pdf`"）
- **绝对不允许**只说"帮我识别一张图片"却不给出文件路径！
"""

INPUT_SECTION_VAGUE = """
## ⚠️ 【最重要】输入文件 — 只做模糊描述，不给路径！
有些 skill 需要用户提供本地文件才能工作。在这条 query 中，你要 **模拟一个懒用户**：
- **只用自然语言描述文件的存在和内容**，但 **绝不写出文件路径或文件名**
- 让 AI 助手自己去寻找或确认文件

**规则**：
- ✅ 正确写法："我之前存了一份销售数据"、"我有一张发票的照片"、"我电脑上有份英文年报"、"我昨天录的那段会议音频"
- ❌ 错误写法："帮我识别 `./receipt.png`"、"分析 `./sales_data.csv`"（不能出现任何 `./xxx` 路径！）
- 文件的描述要足够具体，让人知道大概是什么文件（类型、内容、用途），但不给出精确文件名或路径
- 如果任务需要多个输入文件，每个都只做模糊描述
"""


def _format_other_skills(other_skills: list[SkillInfo]) -> str:
    if not other_skills:
        return "  （无其他可用能力）"
    return "\n".join(f"  - **{skill.name}**: {skill.description}" for skill in other_skills)


def _build_system_prompt_file(vague_input: bool) -> str:
    input_section = INPUT_SECTION_VAGUE if vague_input else INPUT_SECTION_EXPLICIT
    return f"""\
你是一个AI助手的用户模拟器。你的任务是生成真实、自然的用户请求（query）。

## 背景
你正在使用一个拥有多种 skill（技能插件）的 AI 助手平台。每个 skill 提供不同的能力。
你需要根据给定的「主 skill」和「其他可用 skill」，生成一个自然的用户请求。

## 要求
1. **必须使用指定的主 skill**：生成的 query 必须明确触发主 skill 的能力
2. **组合其他能力（必须强连接）**：如果有其他可用能力，可以选择 1~2 个进行组合（如果没有其他可用能力就不用组合）。但组合时 **必须让多个能力之间形成逻辑上的因果链或流水线关系**，前一个步骤的输出要成为后一个步骤的输入或素材。
   - ✅ 好例子："帮我识别 `./invoice_scan.png` 里的内容，然后把识别出来的数据整理到 Excel 表格"
   - ✅ 好例子："帮我搜一下最新的行业资讯，然后基于搜索到的内容帮我录一期播客"
   - ✅ 好例子："帮我把 `./annual_report_en.pdf` 翻译一下，翻译好之后再帮我读出来生成音频"
   - ❌ 坏例子："帮我生成一份行业报告，顺便翻译一下这个文件"（两件独立任务，没有因果关系）
   - ❌ 坏例子："帮我做个图表分析，另外也帮我做个前端页面"（并列罗列，没有数据流动）
   - 如果没有能力能形成有意义的因果链，就只用核心能力，**绝不勉强拼凑**
3. **输出方式（必须遵守）**：从下方给出的「候选输出格式」中 **必须** 选择一个作为最终输出格式。选定后，query 中 **必须** 明确写出输出文件的完整路径和文件名，后面加上 5 个随机数字以防重名（如 `./pet_healthcare_report_12315.pdf`、`./sales_data_12246.csv`），不能只说"保存为 Word 文档"这种模糊表述。即使 skill 本身有默认输出格式，也必须使用候选格式中的一种。
4. **自然真实**：query 要像一个真实用户在工作中向 AI 助手发出的请求，不要像测试用例
5. **话题选择**：从下方给出的「候选话题」中选择一个作为 query 的主题领域，让内容具体、有细节
6. **用中文写 query**
7. **文件名必须用英文，英文后面加上 5 个随机数字以防重名**：所有输入文件路径和输出文件路径的文件名 **必须使用英文命名**（如 `./sales_data_22134.csv`、`./industry_report_23123.pdf`），**禁止使用中文文件名**
8. **禁止透露实现方法**：query 中 **绝对禁止** 出现任何技能名称、技术术语或实现手段。用户只描述「要什么」，绝不说「怎么做」或「用什么工具」。
   - ❌ 禁止出现的词汇/说法："用 OCR 识别"、"用文生图生成"、"用语音合成朗读"、"用翻译功能"、"用搜索能力"、"文字识别技术"、"TTS"、"声音复刻"、任何 skill 名称
   - ✅ 正确写法："帮我识别这张图片里的文字"、"帮我生成一张……的图片"、"帮我把这段话读出来"、"帮我翻译这份文件"、"帮我搜一下……"
   - 核心原则：**query 读起来就是一个普通用户在说话，完全不知道背后有什么 skill 或技术在工作**
{input_section}

## 输出格式
只输出一行 query 文本，不要有多余的解释、引号或前缀。"""


def build_file_prompt(main_skill: SkillInfo, other_skills: list[SkillInfo], *, vague_input: bool) -> str:
    system_prompt = _build_system_prompt_file(vague_input)
    scenario = random.choice(SCENARIOS)
    output_formats = "\n".join(f"  - {item}" for item in random.sample(OUTPUT_FORMATS, 3))
    topic_options = "、".join(random.sample(TOPICS, 3))

    user_lines = [
        "## 核心能力（query 必须覆盖此能力，但禁止在 query 中提及能力名称或技术术语）",
        f"- **能力名称**: {main_skill.name}（⚠️ 禁止在 query 中出现此名称！）",
        f"- **能力描述**: {main_skill.description}",
        "",
        "## 其他可选能力（可组合使用，但禁止在 query 中提及这些能力的名称或技术术语）",
        _format_other_skills(other_skills),
        "",
        "## 场景提示",
        scenario,
        "",
        "## 候选输出格式（必须从中选一个）",
        output_formats,
        "",
        "## 候选话题（从中选择一个作为 query 的主题领域）",
        topic_options,
        "",
        "## ⚠️ 输出文件路径 — 最终检查（不合格将被退回！）",
        "你生成的 query 中 **必须** 包含一个明确的输出文件路径（格式：`./english_filename.ext`），扩展名必须来自上面的候选格式，文件名必须用英文。",
        '- ✅ 正确："...保存到 `./blind_box_sales_analysis.png`"',
        '- ✅ 正确："...导出为 `./coffee_industry_report.pdf`"',
        '- ✅ 正确："...输出到 `./quarter_summary.xlsx`"',
        '- ❌ 错误："...帮我生成一张柱状图，最后把生成的图表保存好"（没有写文件路径！）',
        '- ❌ 错误："...保存为 Word 文档"（没有具体文件名！）',
        '- ❌ 错误："...保存到 `./潮玩盲盒分析.png`"（文件名不能用中文！）',
    ]

    if vague_input:
        user_lines.extend(
            [
                "",
                "## ⚠️ 输入文件 — 再次提醒",
                "这条 query 中涉及的输入文件，**只能用自然语言模糊描述**，绝不能出现 `./xxx` 路径！",
                "让 AI 助手自己去寻找文件。",
            ]
        )

    user_lines.extend(
        [
            "",
            "## 生成",
            "请生成一条自然的中文用户 query，只输出 query 本身，不要有其他内容。",
            "再次确认：(1) query 中是否包含了 `./english_name.ext` 格式的输出文件路径？(2) 文件名是否为英文？如果不满足，请修正！",
        ]
    )
    user_prompt = "\n".join(user_lines)
    return f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"


def _build_system_prompt_chat(vague_input: bool) -> str:
    input_section = INPUT_SECTION_VAGUE if vague_input else INPUT_SECTION_EXPLICIT
    return f"""\
你是一个AI助手的用户模拟器。你的任务是生成真实、自然的用户请求（query）。

## 背景
你正在使用一个拥有多种 skill（技能插件）的 AI 助手平台。每个 skill 提供不同的能力。
你需要根据给定的「主 skill」和「其他可用 skill」，生成一个自然的用户请求。

## 要求
1. **必须使用指定的主 skill**：生成的 query 必须明确触发主 skill 的能力
2. **组合其他 skill（必须强连接）**：如果有其他可用 skill，可以选择 1~2 个进行组合（如果没有其他可用 skill 就不用组合）。但组合时 **必须让多个 skill 之间形成逻辑上的因果链或流水线关系**，前一个 skill 的输出要成为后一个 skill 的输入或素材。
   - ✅ 好例子："先用 OCR 识别 `./invoice_scan.png` 的内容，然后帮我分析发票金额是否合理"（OCR 提取 → 分析）
   - ✅ 好例子："帮我搜索最新的行业资讯，基于搜索结果给我一个投资建议"（搜索 → 分析建议）
   - ✅ 好例子："翻译 `./annual_report_en.pdf` 的内容，然后帮我总结其中的关键要点"（翻译 → 总结）
   - ❌ 坏例子："帮我生成一份行业报告，顺便翻译一下这个文件"（两件独立任务，没有因果关系）
   - ❌ 坏例子："帮我做个图表分析，另外也帮我做个前端页面"（并列罗列，没有数据流动）
   - 如果没有 skill 能形成有意义的因果链，就只用主 skill，**绝不勉强拼凑**
3. **输出方式：直接在对话中回复**。query 中 **不要** 要求保存到文件、导出文件、输出到某个路径。用户只是想在对话中直接得到回答、分析、建议、解读、总结等文字回复。
   - ❌ 禁止出现："保存到"、"导出为"、"输出到"、"生成 xxx 文件"、"./xxx.pdf" 等要求写文件的表述
   - ✅ 正确的表述："帮我分析一下"、"给我一个总结"、"告诉我"、"解读一下"、"给出建议"
4. **自然真实**：query 要像一个真实用户在工作中向 AI 助手发出的请求，不要像测试用例
5. **话题选择**：从下方给出的「候选话题」中选择一个作为 query 的主题领域，让内容具体、有细节
6. **用中文写 query**
7. **输入文件名必须用英文**：如果 query 中涉及输入文件，文件名 **必须使用英文命名**（如 `./sales_data.csv`），**禁止使用中文文件名**
{input_section}

## 输出格式
只输出一行 query 文本，不要有多余的解释、引号或前缀。"""


def build_chat_prompt(main_skill: SkillInfo, other_skills: list[SkillInfo], *, vague_input: bool) -> str:
    system_prompt = _build_system_prompt_chat(vague_input)
    scenario = random.choice(SCENARIOS)
    topic_options = "、".join(random.sample(TOPICS, 3))

    if other_skills:
        other_skills_text = "\n".join(
            f"  - **{skill.name}** (`{skill.slug}`): {skill.description}"
            for skill in other_skills
        )
    else:
        other_skills_text = "  （无其他可用 skill）"

    user_lines = [
        "## 主 skill（必须使用）",
        f"- **名称**: {main_skill.name}",
        f"- **slug**: {main_skill.slug}",
        f"- **描述**: {main_skill.description}",
        "",
        "## 其他可用 skill（可选组合，但必须强连接）",
        other_skills_text,
        "",
        "## 场景提示",
        scenario,
        "",
        "## 候选话题（从中选择一个作为 query 的主题领域）",
        topic_options,
        "",
        "## ⚠️ 最终检查（不合格将被退回！）",
        "- query 中 **不能** 有任何要求保存文件、导出文件的表述（不能出现 ./xxx.pdf、保存到、导出为 等）",
        "- query 只要求 AI 在对话中直接给出回答、分析、建议或总结",
    ]

    if vague_input:
        user_lines.append(
            "- 涉及输入文件时，**只能模糊描述**（如“我有一份销售报告”），绝不能出现 `./xxx` 路径"
        )
    else:
        user_lines.append(
            "- 如果 skill 需要输入文件，必须写出 `./english_filename.ext` 格式的输入路径"
        )

    user_lines.extend(
        [
            "",
            "## 生成",
            "请生成一条自然的中文用户 query，只输出 query 本身，不要有其他内容。",
            "再次确认：query 中是否避免了任何文件输出要求？是否只要求对话回复？",
        ]
    )
    user_prompt = "\n".join(user_lines)
    return f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate query prompts for each workspace skill.")
    parser.add_argument(
        "--workspace-hub",
        type=Path,
        default=None,
        help="Override workspace hub directory. Defaults to config.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace_hub = args.workspace_hub.resolve() if args.workspace_hub else WORKSPACE_HUB

    random.seed(RANDOM_SEED)

    weight_total = sum(TYPE_PROBS)
    percentages = {key: f"{value / weight_total * 100:.0f}%" for key, value in TYPE_WEIGHTS.items()}

    print("Step 1: generate query prompts from existing workspaces")
    print(f"  workspace_hub: {workspace_hub}")
    print(f"  workspace prefix: {WS_PREFIX}")
    print(f"  queries per skill: {QUERIES_PER_SKILL}")
    print(f"  random seed: {RANDOM_SEED}")
    print(
        "  distribution: "
        f"file/explicit {percentages[('file', 'explicit')]} | "
        f"file/vague {percentages[('file', 'vague')]} | "
        f"chat/explicit {percentages[('chat', 'explicit')]} | "
        f"chat/vague {percentages[('chat', 'vague')]}"
    )
    print("=" * 60)

    workspace_specs = collect_workspace_specs(workspace_hub, WS_PREFIX)
    if not workspace_specs:
        raise ValueError(
            f"No workspaces found under {workspace_hub}. "
            f"Expected directories like {WS_PREFIX}*/skills/<skill>/SKILL.md"
        )

    total_skills = sum(len(skills) for _, skills in workspace_specs)
    unique_skills = {skill.slug for _, skills in workspace_specs for skill in skills}
    print(f"\nFound {len(workspace_specs)} workspace directories")
    print(f"Loaded {total_skills} workspace skill entries, {len(unique_skills)} unique skills")

    total_records = 0
    global_counts = {
        "file_explicit": 0,
        "file_vague": 0,
        "chat_explicit": 0,
        "chat_vague": 0,
    }

    for workspace_dir, skills in workspace_specs:
        output_file = workspace_dir / TMP_PROMPTS_FILENAME
        records: list[dict[str, object]] = []

        print(f"\n{workspace_dir.name} ({len(skills)} skills)")
        for skill in skills:
            print(f"  - {skill.slug}: {skill.name}")

        for main_skill in skills:
            other_skills = [skill for skill in skills if skill.slug != main_skill.slug]
            sampled_types = random.choices(TYPE_CHOICES, weights=TYPE_PROBS, k=QUERIES_PER_SKILL)

            for index, (query_type, input_style) in enumerate(sampled_types, start=1):
                vague_input = input_style == "vague"
                if query_type == "chat" and vague_input:
                    prefix = "vague_chat_"
                elif query_type == "chat":
                    prefix = "chat_"
                elif vague_input:
                    prefix = "vague_"
                else:
                    prefix = ""

                query_id = f"{prefix}{workspace_dir.name}__{main_skill.slug}_{index:02d}"
                if query_type == "file":
                    full_prompt = build_file_prompt(main_skill, other_skills, vague_input=vague_input)
                else:
                    full_prompt = build_chat_prompt(main_skill, other_skills, vague_input=vague_input)

                records.append(
                    {
                        "id": query_id,
                        "workspace": workspace_dir.name,
                        "skills": [skill.slug for skill in skills],
                        "query": full_prompt,
                        "skill_main": main_skill.slug,
                        "type": query_type,
                        "input_style": input_style,
                    }
                )

        write_jsonl(output_file, records)

        local_counts = {
            "file_explicit": 0,
            "file_vague": 0,
            "chat_explicit": 0,
            "chat_vague": 0,
        }
        for record in records:
            local_counts[f"{record['type']}_{record['input_style']}"] += 1
        for key, value in local_counts.items():
            global_counts[key] += value

        print(f"  wrote {len(records)} records to {output_file}")
        print(
            "  distribution: "
            f"file/explicit {local_counts['file_explicit']} | "
            f"file/vague {local_counts['file_vague']} | "
            f"chat/explicit {local_counts['chat_explicit']} | "
            f"chat/vague {local_counts['chat_vague']}"
        )
        total_records += len(records)

    print(f"\n{'=' * 60}")
    print(f"Done. Generated {total_records} records across {len(workspace_specs)} workspaces.")
    print(
        "Global distribution: "
        f"file/explicit {global_counts['file_explicit']} | "
        f"file/vague {global_counts['file_vague']} | "
        f"chat/explicit {global_counts['chat_explicit']} | "
        f"chat/vague {global_counts['chat_vague']}"
    )
    print(f"Output file: <workspace_dir>/{TMP_PROMPTS_FILENAME}")


if __name__ == "__main__":
    main()
