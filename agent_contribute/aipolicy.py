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


LINE_LIMIT = 2000
EXCERPT_LIMIT = 300


def ai_policy_excerpts(inspected):
    excerpts, capped, long_lines = [], False, 0
    for item in inspected.get('instructions', []):
        for number, line in enumerate(item['untrusted_text'].splitlines(), 1):
            if len(line) > LINE_LIMIT:
                long_lines += 1  # text past the bound is unscanned, so coverage cannot be complete
            labels = [label for label, pattern in COMPILED if pattern.search(line[:LINE_LIMIT])]
            if not labels:
                continue
            if len(excerpts) == MAX_EXCERPTS:
                capped = True
                continue
            collapsed = ' '.join(line.split())
            excerpts.append({'path': item['path'], 'line': number, 'instruction_sha256': item['sha256'],
                             'patterns': labels, 'untrusted_excerpt': collapsed[:EXCERPT_LIMIT],
                             'excerpt_truncated': len(collapsed) > EXCERPT_LIMIT})
    complete = inspected.get('complete') is True and not capped and not long_lines
    return {'ai_policy_review': 'required', 'coverage': 'complete' if complete else 'incomplete',
            'excerpts_capped': capped, 'lines_partially_scanned': long_lines,
            'excerpts': excerpts,
            'notice': 'Pattern hits are signals for the agent to read in context, not a verdict. Zero hits do not '
                      'mean AI contributions are permitted. Record the review in the contract and disclose it in '
                      'the PR body.'}
