"""Export provider configuration privately inside the legacy API container.

This file is NOT a public migration report; it contains API credentials.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, "/app")
from backend.app.config import get_settings
from backend.app.services.system_settings import get_dingtalk_settings


def main():
    target = Path(sys.argv[1]).resolve()
    root = Path("/app/reports").resolve()
    if root not in target.parents or not target.name.startswith(".weknora-seed-"):
        raise ValueError("Seed must be a private file in the reports directory")
    settings = get_settings()
    embedding_key = os.environ.get("EMBEDDING_API_KEY", "")
    if not settings.dashscope_api_key or not embedding_key or not settings.mineru_api_key:
        raise ValueError("旧系统模型或 MinerU API 配置不完整；不降级为本地模型")
    result = {
        "models": {
            "chat": {"name": settings.llm_model, "source": "remote", "type": "KnowledgeQA",
                     "parameters": {"base_url": settings.llm_base_url, "api_key": settings.dashscope_api_key,
                                    "interface_type": "openai", "provider": "deepseek" if "deepseek" in settings.llm_base_url else "aliyun",
                                    "max_concurrency": 1}},
            "embedding": {"name": os.environ.get("EMBEDDING_API_MODEL", "text-embedding-v4"), "source": "remote", "type": "Embedding",
                          "parameters": {"base_url": os.environ.get("EMBEDDING_API_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                              "api_key": embedding_key, "provider": "aliyun", "interface_type": "openai", "max_concurrency": 1,
                              "embedding_parameters": {"dimension": int(os.environ.get("EMBEDDING_API_DIMENSION", "1024")), "supports_dimension_override": True}}},
        },
        "parser": {"mineru_api_key": settings.mineru_api_key,
                   "mineru_cloud_model": settings.mineru_api_model_version,
                   "mineru_cloud_language": "ch", "mineru_cloud_enable_formula": True,
                   "mineru_cloud_enable_table": True, "mineru_cloud_enable_ocr": True,
                   "chat_parser_engine_rules": [{"file_types": ["pdf"], "engine": "mineru_cloud"}]},
        "dingtalk": get_dingtalk_settings(),
    }
    rerank_key = os.environ.get("RERANK_API_KEY", "")
    if rerank_key:
        result["models"]["rerank"] = {"name": os.environ.get("RERANK_API_MODEL", "qwen3-rerank"),
            "source": "remote", "type": "Rerank", "parameters": {
                "api_key": rerank_key, "base_url": os.environ.get("RERANK_API_BASE_URL", "https://dashscope.aliyuncs.com"),
                "provider": "aliyun", "interface_type": "openai"}}
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False)
    print("Provider configuration exported privately; no credentials printed")


if __name__ == "__main__":
    main()
