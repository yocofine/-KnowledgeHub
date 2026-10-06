"""Generate private staging configuration. This script never starts containers."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import secrets

HERE = Path(__file__).resolve().parent
SECRET_NAMES = ("DB_PASSWORD", "REDIS_PASSWORD", "SYSTEM_AES_KEY", "SYSTEM_SIGNING_KEY", "JWT_SECRET")


def parse_env(text: str) -> dict[str, str]:
    return dict(line.strip().split("=", 1) for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#") and "=" in line)


def validate(values: dict[str, str]) -> None:
    for name in SECRET_NAMES:
        value = values.get(name, "")
        if not value or value == "GENERATE_ME":
            raise ValueError(f"{name} 尚未配置")
        if name == "SYSTEM_AES_KEY":
            if len(value.encode("utf-8")) != 32:
                raise ValueError("SYSTEM_AES_KEY 必须恰好为 32 字节")
        elif len(value) < 24:
            raise ValueError(f"{name} 太短，至少需要 24 个字符")
    if len({values[name] for name in SECRET_NAMES}) != len(SECRET_NAMES):
        raise ValueError("各项凭据不能复用同一个值")
    ports = [int(values.get(name, "0")) for name in ("APP_PORT", "FRONTEND_PORT")]
    if any(not 1024 <= port <= 65535 for port in ports) or ports[0] == ports[1]:
        raise ValueError("前后端端口需不同且位于 1024–65535")
    if values.get("BIND_ADDRESS") != "127.0.0.1" and values.get("DISABLE_REGISTRATION") != "true":
        raise ValueError("公开绑定前必须设置 DISABLE_REGISTRATION=true")


def initialize(target: Path) -> None:
    template = (HERE / "env.example").read_text(encoding="utf-8")
    for name in SECRET_NAMES:
        size = 16 if name == "SYSTEM_AES_KEY" else 32
        template = template.replace(f"{name}=GENERATE_ME", f"{name}={secrets.token_hex(size)}")
    validate(parse_env(template))
    # Exclusive creation: existing encryption keys must NEVER be overwritten.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
        file.write(template)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "check"))
    parser.add_argument("--env-file", type=Path, default=HERE / ".env")
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize(args.env_file)
            print("独立部署配置已生成；未启动容器，未修改旧系统。")
        else:
            validate(parse_env(args.env_file.read_text(encoding="utf-8")))
            print("环境配置检查通过（不输出密钥）。")
    except (OSError, ValueError) as error:
        if isinstance(error, FileExistsError):
            parser.exit(1, "配置已存在；拒绝覆盖。使用 check 检查，不要重置已有密钥。\n")
        parser.exit(1, f"配置失败：{error}\n")


if __name__ == "__main__":
    main()
