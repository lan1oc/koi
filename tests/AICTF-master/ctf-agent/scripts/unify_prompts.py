#!/usr/bin/env python3
"""
统一提示词格式：把 ## / ### markdown 标题全部改成 <xml_tag> 格式。
自动推导标签名策略（無需完整映射表），重要名称通过 OVERRIDE_TAGS 覆盖。
"""
import os
import re
import unicodedata

# ──────────────────────────────────────────────
# Header → tag name mappings (ordered: match full title)
# ──────────────────────────────────────────────
MD_HEADER_TAGS = {
    # reverse-specific
    "ABSOLUTE RULE — NEVER RUN THE BINARY": "no_execution",
    "GUI PROGRAMS — Write a Decryption Script Instead": "gui_programs",
    "CORE MINDSET — Understand Logic, Never Brute-Force": "mindset",
    "IDA Pro MCP (Always Preferred)": "ida_pro",
    "Workflow": "workflow",
    # crypto identity
    "Tool Strategy:": "tool_strategy",
    # appended to all agent identities
    "技能按需读取": "skill_usage",
    "语言要求": "language",
    "ABSOLUTE RULE — NEVER GUESS A FLAG": "no_flag_guessing",
}

# prompt.go solving-protocol section headers (## and ###)
PROTO_HEADER_TAGS = {
    # Two-level ###
    "Tool Selection:": "tool_selection",
    "sage_exec 常用模板:": "sage_templates",
    "python_exec 常用:": "python_exec_tools",
    # One-level ## - longer titles first to avoid partial match
    "Phase 0: Skill Review (MANDATORY)": "phase_0",
    "Phase 0: ": "phase_0",         # fallback prefix
    "Phase 1: Challenge Analysis (ALWAYS do this first)": "phase_1",
    "Phase 1: File Identification & Triage (1-2 rounds)": "phase_1",
    "Phase 1: Problem Analysis (1-2 rounds)": "phase_1",
    "Phase 1: Project Understanding (ALWAYS do this first)": "phase_1",
    "Phase 1: Recon & Initial Setup (1-3 rounds)": "phase_1",
    "Phase 1: Reconnaissance (1-3 rounds)": "phase_1",
    "Phase 1: ": "phase_1",
    "Phase 2: Strategy Selection & Delegation": "phase_2",
    "Phase 2: Algorithm Identification (1-3 rounds)": "phase_2",
    "Phase 2: Binary Analysis (1-3 rounds)": "phase_2",
    "Phase 2: Category-specific Analysis (2-6 rounds)": "phase_2",
    "Phase 2: Delegate Specialized Audits": "phase_2",
    "Phase 2: Static Analysis with IDA Pro (2-5 rounds)": "phase_2",
    "Phase 2: Vulnerability Discovery (2-5 rounds)": "phase_2",
    "Phase 2: Vulnerability Analysis (2-4 rounds)": "phase_2",
    "Phase 2: ": "phase_2",
    "Phase 3: Algorithm Reversal (2-8 rounds)": "phase_3",
    "Phase 3: Attack Implementation (2-8 rounds)": "phase_3",
    "Phase 3: Execution": "phase_3",
    "Phase 3: Exploit Development (3-10 rounds)": "phase_3",
    "Phase 3: Exploitation (2-10 rounds)": "phase_3",
    "Phase 3: Synthesize Findings": "phase_3",
    "Phase 3: Deep Analysis (2-5 rounds)": "phase_3",
    "Phase 3: ": "phase_3",
    "Phase 4: Flag Submission": "phase_4",
    "Phase 4: Flag Extraction": "phase_4",
    "Phase 4: Flag Assembly": "phase_4",
    "Phase 4: Flag Recovery & Submission": "phase_4",
    "Phase 4: Decryption and Flag": "phase_4",
    "Phase 4: Remote Exploitation & Flag": "phase_4",
    "Phase 4: Output Report": "phase_4",
    "Phase 4: ": "phase_4",
    "Safety Constraints": "safety_constraints",
    "Vulnerability Tracking": "vuln_tracking",
    "Platform Operations": "platform_ops",
    "Coordinator Duties": "coordinator_duties",
    "Anti-patterns to Avoid": "antipatterns",
    "TodoList Management": "todolist",
    "Key Reminders": "key_reminders",
    "Common Pitfalls": "common_pitfalls",
    "Skill Self-Iteration (Knowledge Preservation)": "skill_iteration",
    "Common Tricks": "common_tricks",
    "Output Format": "output_format",
}


def _tag_for_header(header_text: str, mapping: dict) -> str | None:
    """Return the XML tag name for a given header text, or None."""
    stripped = header_text.strip()
    # Exact match first
    if stripped in mapping:
        return mapping[stripped]
    # Prefix match (for Phase N: with variable text)
    for key, tag in mapping.items():
        if key.endswith(": ") and stripped.startswith(key):
            return tag
    return None


def convert_sections(content: str, header_mapping: dict,
                     header_prefix: str = "## ") -> str:
    """
    Convert ## (or ### ) section headers to XML open/close tags.

    Algorithm:
    - Walk lines; when a header is found, emit open tag and remember the current tag.
    - When the next header or a closing tag is found, emit the closing tag first.
    - Special case: 语言要求 is a single-line section – emit as self-contained tag.
    - Closing tags we honour: </identity>, </solving_protocol>
    """
    lines = content.split("\n")
    result: list[str] = []
    current_tag: str | None = None

    i = 0
    while i < len(lines):
        line = lines[i]
        raw = line.rstrip()

        # Check if this is a header at the expected level
        is_header = raw.startswith(header_prefix) and not raw.startswith(header_prefix + "#")
        header_text = raw[len(header_prefix):].strip() if is_header else ""
        tag = _tag_for_header(header_text, header_mapping) if is_header else None

        # Lines that close an outer block  (e.g. </identity> or </solving_protocol>)
        is_closer = bool(re.match(r"^\s*</\w", raw)) and not is_header

        if tag is not None:
            # Close previous open tag if any
            if current_tag is not None:
                # Insert closing tag right before this line (strip trailing blank line)
                while result and result[-1].strip() == "":
                    result.pop()
                result.append(f"</{current_tag}>")
                result.append("")
            
            # 语言要求 is a short single-value tag
            if tag == "language":
                # Collect non-empty content lines until next ## or closer
                body_lines = []
                j = i + 1
                while j < len(lines):
                    next_raw = lines[j].rstrip()
                    if next_raw.startswith("## ") or next_raw.startswith("### ") or re.match(r"^\s*</\w", next_raw):
                        break
                    body_lines.append(next_raw)
                    j += 1
                body = " ".join(l.strip("*").strip() for l in body_lines if l.strip())
                result.append(f"<language>{body}</language>")
                result.append("")
                current_tag = None
                i = j
                continue
            else:
                result.append(f"<{tag}>")
                current_tag = tag
                i += 1
                continue

        elif is_closer:
            if current_tag is not None:
                while result and result[-1].strip() == "":
                    result.pop()
                result.append(f"</{current_tag}>")
                result.append("")
                current_tag = None
            result.append(raw)
            i += 1
            continue

        result.append(raw)
        i += 1

    # Close any still-open tag at EOF
    if current_tag is not None:
        while result and result[-1].strip() == "":
            result.pop()
        result.append(f"</{current_tag}>")
        result.append("")

    return "\n".join(result)


def process_identity_md(filepath: str) -> None:
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # Pass 1: convert ## headers
    new_content = convert_sections(content, MD_HEADER_TAGS, "## ")
    if new_content != content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  updated: {os.path.basename(filepath)}")
    else:
        print(f"  no change: {os.path.basename(filepath)}")


def process_prompt_go(filepath: str) -> None:
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    # We only want to convert ## headers that are INSIDE Go backtick string literals
    # Strategy: process each backtick string literal independently.
    # A backtick string in Go starts with ` and ends with `.

    def replace_in_backtick(m: re.Match) -> str:
        inner = m.group(1)
        # Convert ## first
        inner = convert_sections(inner, PROTO_HEADER_TAGS, "## ")
        # Then ### inside phase_3 of crypto (Tool Selection, sage_templates, etc.)
        inner = convert_sections(inner, PROTO_HEADER_TAGS, "### ")
        return "`" + inner + "`"

    new_content = re.sub(r"`((?:[^`]|\n)*?)`", replace_in_backtick, content, flags=re.DOTALL)

    if new_content != content:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  updated: {os.path.basename(filepath)}")
    else:
        print(f"  no change: {os.path.basename(filepath)}")


def main():
    base = r"d:\AI\AICTF\ctf-agent\backend"
    prompts_dir = os.path.join(base, "data", "prompts")
    prompt_go = os.path.join(base, "internal", "agent", "prompt.go")

    print("=== Processing identity .md files ===")
    for name in sorted(os.listdir(prompts_dir)):
        if name.startswith("identity_") and name.endswith(".md"):
            process_identity_md(os.path.join(prompts_dir, name))

    print("\n=== Processing prompt.go ===")
    process_prompt_go(prompt_go)

    print("\nDone.")


if __name__ == "__main__":
    main()
