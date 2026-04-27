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
    ".html (HTML webpage)",
    ".xlsx (Excel spreadsheet)",
    ".png (PNG image)",
    ".docx (Word document)",
    ".md (Markdown document)",
    ".mp3 (MP3 audio)",
    ".pdf (PDF document)",
    ".csv (CSV data file)",
    ".pptx (PowerPoint presentation)",
    ".svg (SVG vector image)",
]

TOPICS = [
    "new energy vehicles", "pet economy", "coffee chain industry", "cross-border e-commerce", "smart home",
    "elder care", "esports industry", "agricultural technology", "online education", "medical aesthetics industry",
    "aerospace", "craft beer", "second-hand luxury goods", "fitness and sports", "maternal and baby products",
    "classical music performances", "intangible cultural heritage handicrafts", "camping and outdoors", "murder mystery game industry", "pet healthcare",
    "sharing economy", "digital collectibles and NFTs", "community group buying", "psychological counseling", "traditional Chinese medicine",
    "new-style tea drinks", "prepared meals", "EV charging infrastructure", "express delivery and logistics", "short-form drama and film",
    "plant-based foods", "autonomous driving", "carbon neutrality", "3D printing", "virtual idols",
    "children's programming", "senior travel", "designer toy blind boxes", "pet food", "homestay operations",
    "quantum computing", "brain-computer interfaces", "synthetic biology", "supply chain finance", "digital RMB",
    "photovoltaic industry", "marine economy", "sports events", "music festival performances", "Hanfu culture",
    "graduate school and overseas study", "vocational training", "robotics industry", "biomedicine", "chip packaging and testing",
    "insurtech", "livestream e-commerce", "cultural and creative products", "warehousing and logistics", "smart cities",
]

SCENARIOS = [
    "Generate a query oriented toward a work reporting scenario.",
    "Generate a query oriented toward a personal learning or research scenario.",
    "Generate a query oriented toward a creative or design scenario.",
    "Generate a query oriented toward a data analysis scenario.",
    "Generate a query oriented toward an automation or productivity improvement scenario.",
    "Generate a query oriented toward a content creation scenario.",
    "Generate a query oriented toward a decision-support scenario.",
    "Generate a query oriented toward a customer service or communication scenario.",
    "Generate a query oriented toward an education or training scenario.",
    "Generate a query for a relatively unique or niche use case.",
]

INPUT_SECTION_EXPLICIT = """
## WARNING: Most Important Requirement for Input Files - Do Not Omit Paths
Many skills require local input files provided by the user. If you use any such skill, whether as the main skill or a combined skill, the query must explicitly include the full path of every required input file without missing any.

**Rules**:
- Every file path must include the `./` prefix, and the file name must be in English and fit the scenario.
- The query must include the file path for every skill that requires an input file.
- Refer to the files naturally in the query, for example: "Help me extract the content from `./receipt_photo.png`" or "I have a file called `./project_plan.pdf`".
- It is absolutely not allowed to say only "Help me process an image" without giving the file path.
"""

INPUT_SECTION_VAGUE = """
## WARNING: Most Important Requirement for Input Files - Use Only Vague Descriptions, No Paths
Some skills require local input files. In this query, you must simulate a lazy user:
- Describe the existence and content of the files only in natural language.
- Never provide any file path or file name.
- Let the AI assistant find or confirm the files on its own.

**Rules**:
- Correct style: "I saved some sales data earlier", "I have a photo of an invoice", "There is an English annual report on my computer", "The meeting audio I recorded yesterday".
- Incorrect style: "Help me process `./receipt.png`", "Analyze `./sales_data.csv`" because no `./xxx` path may appear.
- The file description should be specific enough to indicate what kind of file it is and what it is for, but it must not reveal the exact file name or path.
- If the task needs multiple input files, describe each of them vaguely.
"""


def _format_other_skills(other_skills: list[SkillInfo]) -> str:
    if not other_skills:
        return "  (No other available capabilities)"
    return "\n".join(f"  - **{skill.name}**: {skill.description}" for skill in other_skills)


def _build_system_prompt_file(vague_input: bool) -> str:
    input_section = INPUT_SECTION_VAGUE if vague_input else INPUT_SECTION_EXPLICIT
    return f"""\
You are simulating a user of an AI assistant. Your task is to generate a realistic and natural user request (query).

## Background
You are using an AI assistant platform with multiple skills (skill plugins). Each skill provides different capabilities.
Based on the given main skill and other available skills, generate a natural user request.

## Requirements
1. **The specified main skill must be used**: the generated query must clearly trigger the capability of the main skill.
2. **Combining other capabilities is allowed, but the connection must be strong**: if other capabilities are available, you may combine 1 to 2 of them, and you may also choose not to combine any if none fits well. However, the combined capabilities must form a logical causal chain or pipeline, where the output of one step becomes the input or material for the next.
   - Good example: "Help me extract the content from `./invoice_scan.png`, then organize the extracted data into an Excel spreadsheet."
   - Good example: "Help me look up the latest industry news, then use what you find to help me create a podcast episode."
   - Good example: "Help me translate `./annual_report_en.pdf`, and after that turn the translated content into audio."
   - Bad example: "Help me create an industry report, and also translate this file." This is two unrelated tasks without a causal relationship.
   - Bad example: "Help me analyze a chart, and also build a frontend page." This is just a list of parallel tasks with no data flow.
   - If no meaningful causal chain can be formed, use only the core capability and do not force an awkward combination.
3. **Output format requirement**: you must choose one final output format from the candidate output formats listed below. The query must explicitly include the complete output file path and file name, followed by 5 random digits to avoid collisions, for example `./pet_healthcare_report_12315.pdf` or `./sales_data_12246.csv`. Do not use vague wording such as "save it as a Word document". Even if a skill has a default output format, you must still choose one of the candidate formats.
4. **Keep it natural and realistic**: the query should sound like a real workplace user speaking to an AI assistant, not like a test case.
5. **Topic selection**: choose one topic from the candidate topics below as the domain of the query, and make it concrete and detailed.
6. **Write the final query in Chinese.**
7. **File names must be in English and must end with 5 random digits to avoid collisions**: all input and output file names must be in English, such as `./sales_data_22134.csv` or `./industry_report_23123.pdf`. Chinese file names are not allowed.
8. **Do not reveal implementation details**: the query must not mention any skill names, technical terminology, or implementation methods. The user should describe only what they want, never how to do it or which tool to use.
   - Do not mention technology names or capability labels such as OCR, text-to-image generation, text-to-speech, translation features, search capability, voice cloning, or any skill name.
   - Preferred wording is plain user language such as asking to read text from an image, generate an image, read text aloud, translate a file, or look something up.
   - Core principle: the query should read like something a normal user would say, with no awareness of the underlying skills or technologies.
{input_section}

## Output Format
Output only a single line containing the query text. Do not include any extra explanation, quotation marks, or prefixes."""


def build_file_prompt(main_skill: SkillInfo, other_skills: list[SkillInfo], *, vague_input: bool) -> str:
    system_prompt = _build_system_prompt_file(vague_input)
    scenario = random.choice(SCENARIOS)
    output_formats = "\n".join(f"  - {item}" for item in random.sample(OUTPUT_FORMATS, 3))
    topic_options = "、".join(random.sample(TOPICS, 3))

    user_lines = [
        "## Core Capability (the query must cover this capability, but must not mention the capability name or technical terms)",
        f"- **Capability name**: {main_skill.name} (Do not let this name appear in the query.)",
        f"- **Capability description**: {main_skill.description}",
        "",
        "## Other Optional Capabilities (you may combine them, but do not mention their names or technical terms in the query)",
        _format_other_skills(other_skills),
        "",
        "## Scenario Hint",
        scenario,
        "",
        "## Candidate Output Formats (you must choose one)",
        output_formats,
        "",
        "## Candidate Topics (choose one as the domain of the query)",
        topic_options.replace("、", ", "),
        "",
        "## WARNING: Final Check for the Output File Path",
        "The generated query must include one explicit output file path in the format `./english_filename.ext`. The extension must come from the candidate formats above, and the file name must be in English.",
        '- Correct: "...save it to `./blind_box_sales_analysis.png`"',
        '- Correct: "...export it as `./coffee_industry_report.pdf`"',
        '- Correct: "...output it to `./quarter_summary.xlsx`"',
        '- Incorrect: "...help me generate a bar chart and save it at the end"' ,
        '- Incorrect: "...save it as a Word document"' ,
        '- Incorrect: "...save it to `./chaowan_manghe_analysis.png`" if the file name is not natural English or violates the naming rule.',
    ]

    if vague_input:
        user_lines.extend(
            [
                "",
                "## WARNING: Reminder About Input Files",
                "Any input file mentioned in this query must be described only vaguely in natural language. No `./xxx` path may appear.",
                "Let the AI assistant find the file on its own.",
            ]
        )

    user_lines.extend(
        [
            "",
            "## Generate",
            "Generate one natural Chinese user query. Output only the query itself and nothing else.",
            "Check again: (1) Does the query include an output file path in the format `./english_name.ext`? (2) Is the file name in English? If not, fix it.",
        ]
    )
    user_prompt = "\n".join(user_lines)
    return f"[SYSTEM]\n{system_prompt}\n\n[USER]\n{user_prompt}"


def _build_system_prompt_chat(vague_input: bool) -> str:
    input_section = INPUT_SECTION_VAGUE if vague_input else INPUT_SECTION_EXPLICIT
    return f"""\
You are simulating a user of an AI assistant. Your task is to generate a realistic and natural user request (query).

## Background
You are using an AI assistant platform with multiple skills (skill plugins). Each skill provides different capabilities.
Based on the given main skill and other available skills, generate a natural user request.

## Requirements
1. **The specified main skill must be used**: the generated query must clearly trigger the capability of the main skill.
2. **Combining other skills is allowed, but the connection must be strong**: if other skills are available, you may combine 1 to 2 of them, and you may also choose not to combine any if none fits well. However, the combined skills must form a logical causal chain or pipeline, where the output of one skill becomes the input or material for the next.
   - Good example: "First extract the content from `./invoice_scan.png`, then help me judge whether the invoice amount looks reasonable." This follows an extraction-to-analysis flow.
   - Good example: "Help me search for the latest industry news and give me an investment suggestion based on the results." This follows a search-to-analysis flow.
   - Good example: "Translate the content of `./annual_report_en.pdf`, then help me summarize the key points." This follows a translation-to-summary flow.
   - Bad example: "Help me generate an industry report and also translate this file." This is two unrelated tasks without a causal relationship.
   - Bad example: "Help me do chart analysis, and also build a frontend page." This is just a list of parallel tasks with no data flow.
   - If no meaningful causal chain can be formed, use only the main skill and do not force an awkward combination.
3. **Output mode: reply directly in the conversation**. The query must not ask to save a file, export a file, write to a path, or generate any output file. The user only wants a direct textual reply in the chat, such as an answer, analysis, suggestion, interpretation, or summary.
   - Do not include wording that asks to save or export files, mentions `./xxx.pdf`, or otherwise requests file output.
   - Preferred wording asks for analysis, a summary, an explanation, an interpretation, or a recommendation directly in the chat.
4. **Keep it natural and realistic**: the query should sound like a real workplace user speaking to an AI assistant, not like a test case.
5. **Topic selection**: choose one topic from the candidate topics below as the domain of the query, and make it concrete and detailed.
6. **Write the final query in Chinese.**
7. **Input file names must be in English**: if the query involves input files, their file names must be in English, such as `./sales_data.csv`. Chinese file names are not allowed.
{input_section}

## Output Format
Output only a single line containing the query text. Do not include any extra explanation, quotation marks, or prefixes."""


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
        other_skills_text = "  (No other available skills)"

    user_lines = [
        "## Main Skill (must be used)",
        f"- **Name**: {main_skill.name}",
        f"- **slug**: {main_skill.slug}",
        f"- **Description**: {main_skill.description}",
        "",
        "## Other Available Skills (optional to combine, but the connection must be strong)",
        other_skills_text,
        "",
        "## Scenario Hint",
        scenario,
        "",
        "## Candidate Topics (choose one as the domain of the query)",
        topic_options.replace("、", ", "),
        "",
        "## WARNING: Final Check",
        "- The query must not contain any request to save or export a file, including mentions of `./xxx.pdf` or any other explicit file output.",
        "- The query should ask the AI only for a direct in-chat answer, analysis, suggestion, or summary.",
    ]

    if vague_input:
        user_lines.append(
            "- If input files are involved, describe them only vaguely, such as saying you have a sales report, and never include a `./xxx` path."
        )
    else:
        user_lines.append(
            "- If a skill requires an input file, the query must include the input path in the format `./english_filename.ext`."
        )

    user_lines.extend(
        [
            "",
            "## Generate",
            "Generate one natural Chinese user query. Output only the query itself and nothing else.",
            "Check again: does the query avoid all file-output requests, and does it ask only for a direct conversational reply?",
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
