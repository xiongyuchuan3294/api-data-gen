from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True, slots=True)
class Settings:
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_charset: str = "utf8mb4"
    trace_schema: str = "rrs_test_dev"
    business_schema: str = "aml_new3"
    system_base_url: str = "http://172.21.8.178:9982/aml"
    sys_id: str = "aml_web"


def _load_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    result: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def load_settings(env_file: str | Path | None = None) -> Settings:
    env_path = Path(env_file) if env_file else Path(".env")
    file_values = _load_env_file(env_path)

    def read(key: str, default: str) -> str:
        return os.getenv(key, file_values.get(key, default))

    return Settings(
        mysql_host=read("API_DATA_GEN_MYSQL_HOST", "127.0.0.1"),
        mysql_port=int(read("API_DATA_GEN_MYSQL_PORT", "3306")),
        mysql_user=read("API_DATA_GEN_MYSQL_USER", "root"),
        mysql_password=read("API_DATA_GEN_MYSQL_PASSWORD", ""),
        mysql_charset=read("API_DATA_GEN_MYSQL_CHARSET", "utf8mb4"),
        trace_schema=read("API_DATA_GEN_TRACE_SCHEMA", "rrs_test_dev"),
        business_schema=read("API_DATA_GEN_BUSINESS_SCHEMA", "aml_new3"),
        system_base_url=read("API_DATA_GEN_SYSTEM_BASE_URL", "http://172.21.8.178:9982/aml"),
        sys_id=read("API_DATA_GEN_SYS_ID", "aml_web"),
    )
