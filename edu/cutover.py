"""Back up legacy state and switch only this site's existing HTTPS proxy.

Does not remove any containers, images, data volumes or old project files.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import urllib.request

OLD = Path('/root/Edu-RAG-platform')
NEW = Path('/root/WeKnora-edu')
CONF = Path('/etc/nginx/conf.d/edu-rag.jishang20.com.conf')
BACKUPS = Path('/root/weknora-migration-backups')


def run(arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True, timeout=60)


def prepare():
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix='cutover-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%SZ-'), dir=BACKUPS))
    for source, name in [(CONF, 'nginx-before.conf'), (OLD / '.env', 'legacy.env'), (OLD / 'docker-compose.yml', 'legacy-compose.yml')]:
        shutil.copy2(source, target / name)
        os.chmod(target / name, 0o600)
    dump = target / 'legacy-all-databases.sql'
    descriptor = os.open(dump, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        command = ['docker', 'exec', 'edu-rag-platform-mysql-1', 'sh', '-c',
            'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --triggers --events --all-databases']
        result = subprocess.run(command, stdout=output, stderr=subprocess.PIPE, timeout=120)
    if result.returncode or dump.stat().st_size < 100:
        raise RuntimeError('Legacy database backup failed; proxy not changed')
    marker = NEW / 'edu' / '.cutover-backup.json'
    marker.write_text(json.dumps({'backup': str(target), 'prepared_at': datetime.now(timezone.utc).isoformat()}), encoding='utf-8')
    os.chmod(marker, 0o600)
    print(json.dumps({'backup': str(target), 'database_backup_bytes': dump.stat().st_size, 'switched': False}))


def switch():
    marker = json.loads((NEW / 'edu/.cutover-backup.json').read_text())
    backup = Path(marker['backup']).resolve()
    if BACKUPS.resolve() not in backup.parents or not (backup / 'legacy-all-databases.sql').is_file():
        raise ValueError('Verified backup missing')
    with urllib.request.urlopen('http://127.0.0.1:18080/health', timeout=10) as response:
        if response.status != 200:
            raise RuntimeError('New backend is not healthy')
    with urllib.request.urlopen('http://127.0.0.1:18081/login', timeout=10) as response:
        if response.status != 200:
            raise RuntimeError('New frontend is not healthy')
    # Only replace the known site's config; other sites/certificates stay intact.
    shutil.copy2(NEW / 'edu/nginx-production.conf', CONF)
    try:
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
    except Exception:
        shutil.copy2(backup / 'nginx-before.conf', CONF)
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
        raise
    print(json.dumps({'switched': True, 'frontend_port': 18081, 'backup': str(backup)}))


def rollback():
    backup = Path(json.loads((NEW / 'edu/.cutover-backup.json').read_text())['backup']).resolve()
    if BACKUPS.resolve() not in backup.parents:
        raise ValueError('Invalid rollback target')
    # Restore service availability before moving the public proxy back.
    run(['docker', 'compose', '-f', str(OLD / 'docker-compose.yml'), '--project-directory', str(OLD), 'up', '-d'])
    shutil.copy2(backup / 'nginx-before.conf', CONF)
    run(['nginx', '-t'])
    run(['systemctl', 'reload', 'nginx'])
    print('Legacy site restored; new data left untouched')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'switch', 'rollback'])
    args = parser.parse_args()
    {'prepare': prepare, 'switch': switch, 'rollback': rollback}[args.action]()
