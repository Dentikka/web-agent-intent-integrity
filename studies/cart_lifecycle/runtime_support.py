"""Portable CLI runtime selection; original Windows defaults remain available."""
from __future__ import annotations

import os
from pathlib import Path
import shutil


DISABLED = ('mail,exec,shell_exec,system,passthru,popen,proc_open,fsockopen,'
            'pfsockopen,stream_socket_client,unlink,rmdir')


def php_command(workspace: Path, script: Path, *arguments: object) -> list[str]:
    configured = os.environ.get('DRIFT_PHP_BINARY')
    original = workspace / 'external/php-download/runtime/php.exe'
    executable = configured or (str(original) if original.is_file() else shutil.which('php'))
    if not executable:
        raise ValueError('PHP missing: configure php_binary or install PHP CLI with PDO SQLite, mysqli and mbstring')
    executable = str(Path(executable).expanduser().resolve())
    if not Path(executable).is_file():
        raise ValueError('Configured PHP executable does not exist')
    command = [executable]
    # Linux uses its installed extension configuration; the original portable
    # Windows PHP distribution needs its DLLs explicitly with -n.
    if os.name == 'nt':
        command += ['-n', '-d', 'extension_dir=' + str(Path(executable).parent / 'ext')]
        for extension in ('pdo_sqlite', 'mysqli', 'mbstring'):
            command += ['-d', 'extension=php_' + extension + '.dll']
    command += ['-d', 'allow_url_fopen=0', '-d', 'allow_url_include=0',
                '-d', 'disable_functions=' + DISABLED, str(script)]
    return command + [str(x) for x in arguments]


def control_browser() -> dict:
    channel = os.environ.get('DRIFT_BROWSER_CHANNEL', 'msedge' if os.name == 'nt' else '')
    config = {'browser_args': ['--enable-features=WebMCP']}
    if channel:
        config['browser_channel'] = channel
    if os.environ.get('DRIFT_BROWSER_EXECUTABLE'):
        config['browser_executable'] = os.environ['DRIFT_BROWSER_EXECUTABLE']
    return config
