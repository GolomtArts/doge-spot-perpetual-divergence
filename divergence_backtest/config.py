from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@dataclass(frozen=True)
class BinanceConfig:
    api_key: str = ""
    api_secret: str = ""
    spot_rest_url: str = "https://api.binance.com"
    futures_rest_url: str = "https://fapi.binance.com"

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "BinanceConfig":
        load_env(env_path)
        return cls(
            api_key=os.getenv("BINANCE_API_KEY", ""),
            api_secret=os.getenv("BINANCE_API_SECRET", ""),
            spot_rest_url=os.getenv("BINANCE_SPOT_REST_URL", cls.spot_rest_url),
            futures_rest_url=os.getenv("BINANCE_FUTURES_REST_URL", cls.futures_rest_url),
        )

