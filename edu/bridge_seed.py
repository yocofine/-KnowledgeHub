"""Initialize encrypted extension settings in its dedicated data volume."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from cryptography.fernet import Fernet
from bridge.store import Store


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--store", default="/data/edu.sqlite")
    args = parser.parse_args()
    state = json.loads(args.state.read_text(encoding="utf-8"))
    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    key = os.environ.get("EDU_ENCRYPTION_KEY", "")
    if len(key) < 32:
        raise ValueError("Extension encryption key is not configured")
    store = Store(args.store)
    cipher = Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))
    store.save_settings(cipher, {"rules_kb_id": state["knowledge_bases"]["规则通知"],
        "rules_api_key": state["rules_service_key"], "faq_kb_id": state["knowledge_bases"]["FAQ库"],
        "dingtalk": seed["dingtalk"]})
    print("Extension settings encrypted; historical notifications not sent")


if __name__ == "__main__":
    main()
