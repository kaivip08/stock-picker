"""配置加载模块"""

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """加载配置文件"""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_output_dir(config: dict[str, Any]) -> Path:
    """获取输出目录，自动创建"""
    output_dir = Path(config.get("report", {}).get("output_dir", "./reports"))
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir
