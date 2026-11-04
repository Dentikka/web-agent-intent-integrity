"""Prepare pinned public application code and a new synthetic SQLite fixture."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

from runtime_support import php_command

PACKAGES = (
    ('wordpress', 'https://wordpress.org/wordpress-6.8.2.zip'),
    ('woocommerce', 'https://downloads.wordpress.org/plugin/woocommerce.9.9.5.zip'),
    ('sqlite-database-integration', 'https://downloads.wordpress.org/plugin/sqlite-database-integration.3.1.0.zip'),
)


def extract(archive: Path, destination: Path) -> None:
    base = destination.resolve()
    with zipfile.ZipFile(archive) as zipped:
        for member in zipped.infolist():
            target = (base / member.filename).resolve()
            if not target.is_relative_to(base) or (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Archive contains an unsafe path or symlink')
        zipped.extractall(base)


def download_runtime(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=False)
    downloads = root / 'downloads'
    downloads.mkdir()
    provenance = []
    for name, url in PACKAGES:
        archive = downloads / (name + '.zip')
        with urllib.request.urlopen(url, timeout=120) as response, archive.open('xb') as output:
            shutil.copyfileobj(response, output)
        provenance.append({'url': url, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()})
        destination = root if name == 'wordpress' else root / 'wordpress/wp-content/plugins'
        extract(archive, destination)
    site = root / 'wordpress'
    integration = site / 'wp-content/plugins/sqlite-database-integration'
    shutil.copy2(integration / 'db.copy', site / 'wp-content/db.php')
    mu = site / 'wp-content/mu-plugins'
    mu.mkdir(exist_ok=True)
    shutil.copy2(Path(__file__).with_name('lab-isolation.php'), mu / 'lab-isolation.php')
    (root / 'downloads.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    return site


def prepare(site: Path, output: Path, workspace: Path) -> dict:
    site = site.resolve()
    output = output.resolve()
    if not site.is_dir() or output.is_relative_to(site):
        raise ValueError('Use a valid runtime and a fixture directory outside its code tree')
    for relative in ('wp-settings.php', 'wp-content/db.php', 'wp-content/mu-plugins/lab-isolation.php',
                     'wp-content/plugins/woocommerce/woocommerce.php',
                     'wp-content/plugins/sqlite-database-integration/constants.php'):
        if not (site / relative).is_file():
            raise ValueError('Prepared runtime is missing ' + relative)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'wc-logs').mkdir()
    command = php_command(workspace, Path(__file__).with_name('prepare_fixture.php'), site, output)
    with (output / 'prepare.log').open('w', encoding='utf-8') as log:
        process = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    transcript = (output / 'prepare.log').read_text(encoding='utf-8', errors='replace')
    if process.returncode or '\nFIXTURE_RESULT:' not in transcript:
        raise RuntimeError('Fixture preparation failed; inspect prepare.log. Existing data are not overwritten.')
    result = json.loads(transcript.rsplit('\nFIXTURE_RESULT:', 1)[1].splitlines()[0])
    result['database_sha256'] = hashlib.sha256((output / 'state.sqlite').read_bytes()).hexdigest()
    (output / 'fixture.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(__doc__)
    runtime = parser.add_mutually_exclusive_group(required=True)
    runtime.add_argument('--site', type=Path, help='Existing prepared immutable WP/WC source code')
    runtime.add_argument('--download-runtime', type=Path, help='Fresh directory for pinned public downloads')
    parser.add_argument('--out', type=Path, required=True, help='Fresh fixture directory')
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    args = parser.parse_args()
    site = args.site if args.site else download_runtime(args.download_runtime)
    print(json.dumps(prepare(site, args.out, args.workspace), indent=2))


if __name__ == '__main__':
    main()
