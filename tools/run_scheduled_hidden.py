"""Windowless Windows Task Scheduler entry point; keep the existing runners."""

import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--powershell', required=True)
    parser.add_argument('--task', choices=('Intake', 'Queue', 'Daily'), required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    runner = root / 'tools' / ('run_scroll_daily.ps1' if args.task == 'Daily' else 'run_scroll_background.ps1')
    command = [args.powershell, '-NoLogo', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-File', str(runner)]
    if args.task != 'Daily':
        command += ['-Mode', args.task]
    logs = root / 'data' / 'agent' / 'scheduler'
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / (args.task.lower() + '.log')).open('a', encoding='utf-8') as log:
        log.write(datetime.now().astimezone().isoformat() + ' starting ' + args.task + '\n')
        log.flush()
        try:
            return subprocess.run(command, cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                  creationflags=subprocess.CREATE_NO_WINDOW).returncode
        except Exception:
            traceback.print_exc(file=log)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
