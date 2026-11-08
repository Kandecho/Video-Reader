"""Shared bounded host invocation; no personal feed, account state or delivery."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import tomllib
import urllib.request

from video_reader.common import ReaderError, write_json

def diagnostics(path):
    """Extract error events from a bounded log tail, never the prompt or auth config."""
    path = Path(path)
    if not path.is_file():
        return {'log_path': str(path), 'message': None, 'events': []}
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        lines = stream.read().decode('utf-8', errors='replace').splitlines()
    events = []
    for line in lines:
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        if item.get('type') == 'turn.failed':
            message = (item.get('error') or {}).get('message')
        elif item.get('type') == 'error':
            message = item.get('message')
        else:
            continue
        if isinstance(message, str):
            events.append({'type': item['type'], 'message': message[:2000]})
    return {'log_path': str(path), 'message': events[-1]['message'] if events else None, 'events': events[-8:]}


class HostError(ReaderError):
    def __init__(self, message, log_path, *, returncode=None, timeout=False):
        self.details = {**diagnostics(log_path), 'returncode': returncode, 'timed_out': timeout}
        cause = self.details['message']
        self.category = ('host_timeout' if timeout else 'host_transport' if cause and any(
            word in cause.lower() for word in ('timed out', 'connection', 'websocket', 'transport', 'dns', 'workspace routing')) else 'host_failed')
        super().__init__(message + (f': {cause}' if cause else '') + f'; log: {log_path}')


def model_options(options):
    if options.get('model'):
        return ['--model', options['model']]
    home = Path(os.environ.get('CODEX_HOME', Path.home() / '.codex'))
    path = home / 'config.toml'
    if not path.is_file():
        return []
    values = tomllib.loads(path.read_text(encoding='utf-8'))
    if values.get('model_provider') not in (None, 'openai'):
        raise ReaderError('Set agent.host.model or use a configured host adapter for a non-OpenAI provider')
    result = ['--model', values['model']] if values.get('model') else []
    if values.get('model_reasoning_effort'):
        result.extend(['-c', 'model_reasoning_effort=' + json.dumps(values['model_reasoning_effort'])])
    return result


def resolve_executable(options):
    configured = options.get('executable')
    if configured:
        executable = str(Path(configured).resolve()) if Path(configured).is_file() else shutil.which(configured)
        if executable:
            return executable
        raise ReaderError(f'Configured Codex CLI not found: {configured}; set agent.host.executable to null for automatic discovery')
    executable = shutil.which('codex')
    if executable:
        return executable
    if os.name == 'nt':
        directory = Path.home() / 'AppData' / 'Local' / 'OpenAI' / 'Codex' / 'bin'
        candidates = [path for path in directory.glob('*/codex.exe') if path.is_file()]
        if candidates:
            return str(max(candidates, key=lambda path: path.stat().st_mtime_ns))
    raise ReaderError('Codex CLI not found; configure agent.host.executable or finish this round through the host tools')


def host_environment():
    """Bridge the existing Windows system proxy to the CLI without changing user settings."""
    environment=os.environ.copy()
    # An explicitly configured (even empty) proxy wins. Do not mix two proxy setups.
    if os.name!='nt' or any(key.lower() in ('http_proxy','https_proxy','all_proxy') for key in environment):
        return environment
    registry_proxies=getattr(urllib.request,'getproxies_registry',lambda:{})()
    for scheme in ('http','https'):
        if registry_proxies.get(scheme):
            environment[scheme.upper()+'_PROXY']=registry_proxies[scheme]
    return environment


def invoke(prompt, images, schema_value, directory, options, *, progress=None,
           executable=None, model_args=None, output_name='response.json', checkpoint=None):
    """One isolated attempt; callers own checkpoints and semantic validation."""
    work = Path(directory).resolve()
    work.mkdir(parents=True, exist_ok=True)
    schema, output, log_path = work/'schema.json', work/output_name, work/'host.log'
    if output.exists():
        raise ReaderError('Host attempt directory is already used; choose a new attempt ID')
    write_json(schema, schema_value)
    command = [executable or resolve_executable(options), 'exec', '--ephemeral', '--ignore-user-config',
        '--sandbox', 'read-only', '--skip-git-repo-check', '-c', 'approval_policy="never"',
        '-c', 'features.shell_tool=false', '--disable', 'apps', '--disable', 'plugins',
        '--enable', 'skip_host_skill_discovery', '-c', 'project_doc_max_bytes=0',
        '--output-schema', str(schema), '--output-last-message', str(output),
        '--color', 'never', '--json', *(model_options(options) if model_args is None else model_args)]
    for path in images:
        command.extend(['--image', str(path)])
    command.append('-')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=work, stdin=subprocess.PIPE, stdout=log, stderr=log,
            text=True, encoding='utf-8', creationflags=flags, env=host_environment())
        try:
            from .processes import identity
            write_json(work/'host-process.json',identity(process.pid))
            if progress:
                progress(host_pid=process.pid, host_log=str(log_path))
            if checkpoint is None:
                process.communicate(prompt, timeout=options.get('timeout_seconds', 300))
            else:
                deadline=time.monotonic()+options.get('timeout_seconds',300)
                remaining_input=prompt
                while True:
                    checkpoint()
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise subprocess.TimeoutExpired(command,options.get('timeout_seconds',300))
                    try:
                        process.communicate(remaining_input,timeout=min(1,remaining))
                        break
                    except subprocess.TimeoutExpired:
                        remaining_input=None
                checkpoint()
        except BaseException as error:
            if os.name == 'nt':
                subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'], capture_output=True,
                    timeout=15, creationflags=flags)
            else:
                process.kill()
            process.wait(timeout=15)
            if isinstance(error, subprocess.TimeoutExpired):
                raise HostError('Task host timed out', log_path, timeout=True) from None
            raise
    if process.returncode or not output.is_file():
        raise HostError('Task host failed', log_path, returncode=process.returncode)
    try:
        return json.loads(output.read_text(encoding='utf-8'))
    except ValueError as error:
        raise HostError('Task host returned invalid JSON', log_path, returncode=process.returncode) from error


