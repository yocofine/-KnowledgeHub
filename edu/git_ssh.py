"""Local Git SSH transport over port 443 when Windows OpenSSH is unavailable.

Uses an ephemeral repository-scoped deploy key and pinned GitHub host keys.
No credentials are part of this file. Only this project's Git remote is allowed.
"""
import os
from pathlib import Path
import re
import sys
import threading

import paramiko

HERE = Path(__file__).resolve().parent


def main():
    if os.name == "nt":
        import msvcrt
        # Git pack streams contain arbitrary bytes (including CR/LF and Ctrl-Z).
        # Windows CRT text mode would silently corrupt or truncate the stream.
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    if sys.argv[1:] == ["-G", "github.com"]:
        return 0
    if len(sys.argv) < 3 or sys.argv[-2] not in {"github.com", "git@github.com"}:
        raise ValueError("Only github.com is supported")
    command = sys.argv[-1]
    if not re.fullmatch(r"git-(?:receive|upload)-pack 'yocofine/WeKnora-edu\.git'", command):
        raise ValueError("Refusing unrelated repository command")
    client = paramiko.SSHClient()
    client.load_host_keys(str(HERE / ".github-known-hosts"))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect("ssh.github.com", port=443, username="git",
                   key_filename=str(HERE / ".github-deploy-key"),
                   allow_agent=False, look_for_keys=False,
                   timeout=12, banner_timeout=12, auth_timeout=12)
    channel = client.get_transport().open_session(timeout=20)
    channel.exec_command(command)

    def send_stdin():
        try:
            while True:
                data = os.read(sys.stdin.fileno(), 65536)
                if not data:
                    channel.shutdown_write()
                    return
                channel.sendall(data)
        except (EOFError, OSError):
            return

    def receive_stderr():
        while True:
            data = channel.recv_stderr(65536)
            if not data:
                return
            sys.stderr.buffer.write(data)
            sys.stderr.buffer.flush()

    threading.Thread(target=send_stdin, daemon=True).start()
    threading.Thread(target=receive_stderr, daemon=True).start()
    try:
        while True:
            data = channel.recv(65536)
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        return channel.recv_exit_status()
    finally:
        channel.close()
        client.close()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"Git SSH transport failed: {type(error).__name__}: {error}", file=sys.stderr)
        sys.exit(1)
