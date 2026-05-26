"""Runtime configuration, loaded from environment variables (or .env file).

All settings have safe defaults so the app runs out-of-the-box for public Azure.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    # Optional: load a .env file from the project root if python-dotenv is installed.
    from dotenv import load_dotenv

    _ROOT = Path(__file__).resolve().parent.parent
    load_dotenv(_ROOT / ".env", override=False)
except ImportError:  # pragma: no cover
    pass


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    # HTTP server
    host: str = os.environ.get("HOST", "127.0.0.1")
    port: int = _int("PORT", 8765)
    log_level: str = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Caching
    cache_ttl: int = _int("CACHE_TTL", 300)
    http_timeout: float = float(os.environ.get("HTTP_TIMEOUT", "60"))

    # Azure cloud (override for sovereign clouds e.g. AzureUSGovernment, AzureChinaCloud)
    arm_endpoint: str = os.environ.get(
        "ARM_ENDPOINT", "https://management.azure.com"
    ).rstrip("/")
    arm_resource: str = os.environ.get(
        "ARM_RESOURCE", "https://management.azure.com"
    ).rstrip("/")

    # API versions (override only if you need to pin)
    api_subscriptions: str = os.environ.get("API_SUBSCRIPTIONS", "2022-12-01")
    api_locations: str = os.environ.get("API_LOCATIONS", "2022-12-01")
    api_cogsvc: str = os.environ.get("API_COGSVC", "2024-10-01")
    api_cogsvc_fallback: str = os.environ.get("API_COGSVC_FALLBACK", "2023-05-01")
    api_aml: str = os.environ.get("API_AML", "2024-10-01-preview")


settings = Settings()
