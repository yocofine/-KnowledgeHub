"""Generate a private login note without exposing tokens or provider credentials."""
import argparse
import json
import os
from pathlib import Path


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding='utf-8'))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        output.write('# 新系统管理员登录信息（私密）\n\n')
        output.write('地址：https://edu-rag.jishang20.com\n\n')
        output.write('登录邮箱：' + state['email'] + '\n\n')
        output.write('初始密码：`' + state['password'] + '`\n\n')
        output.write('首次登录后请在账户设置修改密码。不要公开分享本文件。\n')
    print('Private login note generated; password not printed')
