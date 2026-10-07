"""Set only deployment-owned public origin/registration values; preserve keys."""
import argparse
from pathlib import Path
import tempfile
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--origin', required=True)
    args = parser.parse_args()
    if args.origin != 'https://edu-rag.jishang20.com':
        raise ValueError('Unexpected site origin')
    values = {'APP_EXTERNAL_URL': args.origin, 'FRONTEND_BASE_URL': args.origin, 'DISABLE_REGISTRATION': 'true'}
    lines = args.env_file.read_text(encoding='utf-8').splitlines()
    found = set()
    for index, line in enumerate(lines):
        name = line.split('=', 1)[0]
        if name in values:
            lines[index] = name + '=' + values[name]
            found.add(name)
    lines.extend(name + '=' + value for name, value in values.items() if name not in found)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=args.env_file.parent, delete=False) as output:
        output.write('\n'.join(lines) + '\n')
        target = Path(output.name)
    os.chmod(target, 0o600)
    target.replace(args.env_file)
    print('Production origin configured; registration disabled; existing keys preserved')


if __name__ == '__main__':
    main()
