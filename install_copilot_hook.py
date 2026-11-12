"""Install or remove the CodexApprover GitHub Copilot hook in the user-level hooks folder.

    python install_copilot_hook.py              # install / update
    python install_copilot_hook.py --uninstall  # remove
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
HOOKS_DIR = os.path.join(os.environ.get('COPILOT_HOME') or os.path.join(os.path.expanduser('~'), '.copilot'), 'hooks')
TARGET = os.path.join(HOOKS_DIR, 'codex-approver.json')


def hook_config():
    python = sys.executable
    script = os.path.join(HERE, 'copilot_approver_hook.py')
    command = f'"{python}" "{script}"'
    return {
        'version': 1,
        'hooks': {
            'permissionRequest': [{
                'type': 'command',
                'powershell': f'& {command}',
                'bash': command,
                'timeoutSec': 10,
            }],
        },
    }


def main():
    if '--uninstall' in sys.argv:
        if os.path.exists(TARGET):
            os.remove(TARGET)
            print(f'Removed {TARGET}')
        else:
            print(f'Not installed: {TARGET}')
        return
    os.makedirs(HOOKS_DIR, exist_ok=True)
    with open(TARGET, 'w', encoding='utf-8') as f:
        json.dump(hook_config(), f, indent=2)
        f.write('\n')
    print(f'Installed {TARGET}\nStart a new Copilot session for it to take effect.')


if __name__ == '__main__':
    main()
