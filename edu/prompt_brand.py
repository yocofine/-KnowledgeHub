"""Migrate only old assistant identity lines, preserving custom agent settings."""
import copy
import re


def rebrand_saved_intents(config):
    updated = copy.deepcopy(config)
    intents = updated.get('intent_prompts')
    if not isinstance(intents, dict):
        return updated
    for intent, prompt in intents.items():
        if not isinstance(prompt, str):
            continue
        lines = prompt.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if not re.match(r'^\s*You are\b', line):
                continue
            line = re.sub(r'\bWeKnora\b', '智导 KnowledgeHub', line, flags=re.I)
            line = re.sub(r' developed by Tencent\b', '', line, flags=re.I)
            lines[index] = line
        intents[intent] = ''.join(lines)
    return updated
