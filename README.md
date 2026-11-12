# CodexApprover

A Windows KeymouseGo plugin that recognizes Codex CLI and Claude Code approval prompts and sends the matching approval keys directly to the console, without changing window focus or using screen coordinates.

The default rules automatically approve matching requests, including persistent or session approval choices when available.

## Usage

1. Place this folder in KeymouseGo's plugins directory, keeping the name `CodexApprover`.
2. Enable the plugin in KeymouseGo.
3. Load `codex_approver_loop.json5`, set run times to `1`, and start it. The script loops until stopped.
4. Adjust process names, prompt rules, polling, and retry settings in `manifest.json5` as needed.

The plugin uses KeymouseGo's `Plugin.Interface` and `loguru` environment. It is intended to run inside the windowed KeymouseGo application rather than as a standalone Python script.

Elevated Codex terminals require KeymouseGo to run as administrator. Unrecognized prompts and prompts that remain open after retries trigger an alert; diagnostic console text is saved under `logs/`.

## GitHub Copilot hook

Copilot (VS Code Copilot sessions and Copilot CLI) prompts in its own UI rather than a console, so it uses a `permissionRequest` hook instead of KeymouseGo:

```powershell
python install_copilot_hook.py              # writes %USERPROFILE%\.copilot\hooks\codex-approver.json
python install_copilot_hook.py --uninstall  # removes it
```

Start a new Copilot session after installing. By default the hook approves every permission request. Optional rules in `copilot_hook_config.json`: `ask_patterns` show the normal prompt for matching tool input, `deny_patterns` block outright and `ask_tools` always prompt for the named tools. Set `enabled` to `false` to disable without uninstalling. Decisions are logged to `logs/copilot_hook.log`. Sandbox-escape requests always prompt because Copilot ignores hook approval for them, and errors fall through to the normal prompt.

The installer stores the absolute paths of the current Python interpreter and this folder, so rerun it after moving either. Organization policy can disable user hooks.

## Files

- `CodexApprover.py`: plugin entry point, prompt matching, retries, and alerts.
- `codex_console.py`: Windows console access and key injection using `ctypes`.
- `manifest.json5`: plugin metadata and configurable prompt rules.
- `codex_approver_loop.json5`: looping KeymouseGo script that calls `codex_scan`.
- `copilot_approver_hook.py`: GitHub Copilot `permissionRequest` hook.
- `copilot_hook_config.json`: hook rules.
- `install_copilot_hook.py`: installs or removes the user-level hook.
