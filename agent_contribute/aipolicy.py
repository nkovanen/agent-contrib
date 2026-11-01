"""Opt-in scan of fetched instruction files for AI-contribution statements (#8). Signals, never a verdict."""
import re

MAX_EXCERPTS = 200
PATTERNS = [('AI-generated', r'\bAI[- ]generated\b'), ('AI-assisted', r'\bAI[- ]assisted\b'),
            ('LLM', r'\bLLMs?\b'), ('large language model', r'\blarge language models?\b'),
            ('generative AI', r'\bgenerative AI\b'), ('artificial intelligence', r'\bartificial intelligence\b'),
            ('Copilot', r'\bCopilot\b'), ('ChatGPT', r'\bChatGPT\b'),
            ('machine-generated', r'\bmachine[- ]generated\b'), ('no AI', r'\bno AI\b'),
            ('AI tools', r'\bAI (?:tools?|agents?|contributions?|code)\b')]
COMPILED = [(label, re.compile(pattern, re.IGNORECASE)) for label, pattern in PATTERNS]


def ai_policy_excerpts(inspected):
    excerpts, truncated = [], False
    for item in inspected.get('instructions', []):
        for number, line in enumerate(item['untrusted_text'].splitlines(), 1):
            labels = [label for label, pattern in COMPILED if pattern.search(line[:2000])]
            if not labels:
                continue
            if len(excerpts) == MAX_EXCERPTS:
                truncated = True
                break
            excerpts.append({'path': item['path'], 'line': number, 'instruction_sha256': item['sha256'],
                             'patterns': labels, 'untrusted_excerpt': ' '.join(line.split())[:300]})
    coverage = 'complete' if inspected.get('complete') is True and not truncated else 'incomplete'
    return {'ai_policy_review': 'required', 'coverage': coverage, 'truncated': truncated,
            'excerpts': excerpts,
            'notice': 'Pattern hits are signals for the agent to read in context, not a verdict. Zero hits do not '
                      'mean AI contributions are permitted. Record the review in the contract and disclose it in '
                      'the PR body.'}
