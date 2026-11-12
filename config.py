"""Project configuration loader.

Loads configuration from config.json and environment variables.
Can be imported by any module to access global configuration.
"""

import json
import os
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config() -> dict:
    """Load configuration from config.json."""
    with open(_CONFIG_PATH, "r") as f:
        return json.load(f)


# Load configuration on import
_config = load_config()


def get(key: str, default=None):
    """Get a config value using dot notation.

    Examples:
        get("aws.region")
        get("orders.bucket_name")
    """
    keys = key.split(".")
    value = _config
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
        else:
            return default
    return value if value is not None else default


def get_aws_region() -> str:
    """Get AWS region from config or environment."""
    return os.getenv("AWS_REGION", get("aws.region", "us-east-1"))


def get_orders_bucket() -> str:
    """Get orders bucket name from config."""
    return get("orders.bucket_name", "orders-service-db")


def get_orders_data_path() -> str:
    """Get orders data path from config."""
    return get("orders.data_path", "data/orders/orders.json")
