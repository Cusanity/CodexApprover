"""GitHub Copilot `permissionRequest` hook: auto-approves tool permission requests.

Reads the hook payload (JSON) from stdin and writes a decision to stdout:
  {"behavior": "allow"}                     -> approve without prompting
  {"behavior": "deny", "message": "..."}    -> block
  {}                                        -> fall through to Copilot's normal prompt
Rules live in copilot_hook_config.json next to this file. Any error falls through to the prompt.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
CONFIG_PATH = os.path.join(HERE, 'copilot_hook_config.json')
LOG_PATH = os.path.join(HERE, 'logs', 'copilot_hook.log')


def _strings(value):
    """Yield every string inside a (possibly nested) tool input."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def _first(payload, *keys):
    return next((payload[k] for k in keys if k in payload), None)


def decide(payload, config):
    """Return (decision dict, reason) for a permissionRequest payload."""
    if not config.get('enabled', True):
        return {}, 'disabled'
    tool = str(_first(payload, 'toolName', 'tool_name') or '')
    tool_input = _first(payload, 'toolInput', 'toolArgs', 'tool_input')
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            pass
    if isinstance(tool_input, dict) and tool_input.get('requestSandboxBypass'):
        # Copilot always prompts for sandbox escapes; an allow here would be ignored.
        return {}, 'sandbox bypass'
    text = '\n'.join(_strings(tool_input))
    for pattern in config.get('deny_patterns', []):
        if re.search(pattern, text):
            return {'behavior': 'deny', 'message': f'Blocked by CodexApprover hook rule: {pattern}'}, pattern
    if tool in config.get('ask_tools', []):
        return {}, f'ask tool {tool}'
    for pattern in config.get('ask_patterns', []):
        if re.search(pattern, text):
            return {}, f'ask pattern {pattern}'
    return {'behavior': 'allow'}, 'allow'


def _log(config, tool, reason, payload):
    if not config.get('log', True):
        return
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        detail = json.dumps(_first(payload, 'toolInput', 'toolArgs', 'tool_input'), ensure_ascii=False)[:300]
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")}\t{tool}\t{reason}\t{detail}\n')
    except OSError:
        pass


def main():
    decision, config, payload = {}, {}, {}
    try:
        with open(CONFIG_PATH, encoding='utf-8') as f:
            config = json.load(f)
        payload = json.loads(sys.stdin.buffer.read().decode('utf-8-sig') or '{}')
        decision, reason = decide(payload, config)
        _log(config, _first(payload, 'toolName', 'tool_name'), reason, payload)
    except Exception as e:  # never crash: fall through to the normal Copilot prompt
        decision = {}
        _log(config or {'log': True}, '?', f'error: {e}', payload if isinstance(payload, dict) else {})
    sys.stdout.write(json.dumps(decision))
    return 0


if __name__ == '__main__':
    sys.exit(main())
