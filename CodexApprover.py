import os
import re
import time
from typing import Callable, Dict, List

from loguru import logger

from Plugin.Interface import PluginInterface

import codex_console as cc

LOG_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'logs')


def _nonblank(lines: List[str]) -> List[str]:
    return [ln for ln in lines if ln.strip()]


class CodexApprover(PluginInterface):
    """Call `codex_scan` from a looping script step; it answers any Codex prompt it recognizes."""

    def __init__(self, manifest: Dict):
        super().__init__(manifest)
        m = self.meta
        self.rules = [(r['name'], re.compile(r['footer']), re.compile(r['option']), r['keys'])
                      for r in getattr(m, 'rules', [])]
        self.alert_re = re.compile(getattr(m, 'alert_hint', r'(?i)esc to cancel'))
        self.attempts: Dict[tuple, int] = {}
        self.alerted = set()
        self.denied = set()

    def register_functions(self) -> Dict[str, Callable]:
        return {'codex_scan': self.codex_scan}

    def register_record_functions(self) -> List[Callable]:
        return []

    def _match(self, lines: List[str]):
        """Return ('rule', [(name, keys), ...] in priority order) | ('alert', []) | None for a screen."""
        lines = _nonblank(lines)
        fw, ow = self.meta.footer_window, self.meta.option_window
        tail = lines[-fw:]
        found = []
        for name, footer_re, option_re, keys in self.rules:
            for fi, line in enumerate(tail):
                if footer_re.search(line):
                    above = lines[:len(lines) - len(tail) + fi][-ow:]
                    m = next(filter(None, (option_re.search(o) for o in above)), None)
                    if m:
                        # '{n}' sends the option number captured by the rule's (?P<n>...) group.
                        found.append((name, [d for k in keys for d in (list(m['n']) if k == '{n}' else [k])]))
                        break
        if found:
            return 'rule', found
        if any(self.alert_re.search(ln) for ln in tail):
            return 'alert', []
        return None

    def _dump(self, pid: int, lines: List[str]):
        os.makedirs(LOG_DIR, exist_ok=True)
        path = os.path.join(LOG_DIR, f'unknown_prompt_{pid}_{time.strftime("%H%M%S")}.txt')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        return path

    def _handle(self, pid: int) -> bool:
        try:
            console_id, lines = cc.read_screen(pid)
        except OSError as e:
            if e.errno == cc.ERROR_ACCESS_DENIED and pid not in self.denied:
                # Elevated (admin) Codex terminal: Windows blocks a non-elevated process from attaching.
                self.denied.add(pid)
                cc.beep()
                logger.warning(f'Codex pid {pid}: access denied (elevated terminal). '
                               f'Run KeymouseGo as administrator to handle elevated Codex sessions.')
            return False  # no console (app-server daemon), gone, or elevated
        result = self._match(lines)
        if result is None:
            return False
        kind, candidates = result
        sig = (pid, console_id, hash(tuple(_nonblank(lines)[-self.meta.footer_window:])))
        if kind == 'alert':
            if sig not in self.alerted:
                self.alerted.add(sig)
                cc.beep()
                logger.warning(f'Codex pid {pid}: unrecognized prompt, saved to {self._dump(pid, lines)}')
            return True
        # Prefer the first rule that has not yet failed max_attempts times on this prompt.
        pick = next(((name, keys) for name, keys in candidates
                     if self.attempts.get((sig, name), 0) < self.meta.max_attempts), None)
        if pick is None:
            if sig not in self.alerted:
                self.alerted.add(sig)
                cc.beep()
                names = ', '.join(n for n, _ in candidates)
                logger.warning(f'Codex pid {pid}: rules {names} did not clear the prompt, saved to '
                               f'{self._dump(pid, lines)}')
            return True
        name, keys = pick
        self.attempts[(sig, name)] = self.attempts.get((sig, name), 0) + 1
        cc.send_keys(pid, keys)
        logger.info(f'Codex pid {pid}: rule {name} -> {keys}')
        deadline = time.time() + self.meta.verify_ms / 1000
        while time.time() < deadline:
            time.sleep(0.1)
            try:
                cleared = self._match(cc.read_screen(pid)[1]) != result
            except OSError:
                cleared = True
            if cleared:
                # Codex often repeats an identical prompt (same command/input); only failures should count.
                self.attempts.pop((sig, name), None)
                self.alerted.discard(sig)
                return True
        return True

    def codex_scan(self, json_object=None):
        self.scans = getattr(self, 'scans', 0) + 1
        pids = [pid for pid, _ in cc.list_processes(self.meta.process_names)]
        if self.scans == 1 or self.scans % 150 == 0:
            logger.info(f'codex_scan #{self.scans}: codex pids {pids}')
        if len(self.attempts) > 200:
            self.attempts.clear()
            self.alerted.clear()
        for pid in pids:
            try:
                self._handle(pid)
            except Exception as e:
                logger.error(f'Codex pid {pid}: {e}')
        if not pids:
            time.sleep(self.meta.idle_poll_ms / 1000)
