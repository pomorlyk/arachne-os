from __future__ import annotations

import os
from pathlib import Path
import subprocess
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_ROOT = Path(__file__).resolve().parent.parent


class ArachneSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_api_key: str = Field(default="")
    llm_base_url: str = Field(default="https://api.deepseek.com/v1")
    llm_model_l2_fast: str = Field(default="deepseek-chat")
    llm_model_l3_reasoner: str = Field(default="deepseek-chat")
    llm_timeout_seconds: float = Field(default=25.0)

    spider_max_span: int = Field(default=5)
    node_dehydrate_idle_seconds: int = Field(default=180)
    sandbox_timeout_seconds: float = Field(default=3.0)
    arena_min_match_rate: float = Field(default=0.98)
    replaceability_transition_threshold: float = Field(default=90.0)

    sqlite_db_url: str = Field(
        default=f"sqlite+aiosqlite:///{(BASE_ROOT / 'arachne_hot_state.db').as_posix()}"
    )
    vault_storage_dir: Path = Field(default=BASE_ROOT / "vault_storage")
    sandbox_workspace_dir: Path = Field(default=BASE_ROOT / "sandbox_workspace")

    wecom_adapter_mode: str = Field(default="LOCAL_SIMULATOR")
    wecom_bot_id: str = Field(default="")
    wecom_bot_secret: str = Field(default="")
    wecom_ws_endpoint: str = Field(default="wss://openws.work.weixin.qq.com")
    wecom_webhook_key: str = Field(default="")

    # 外部真实连接器 (HTTP Webhook / 企微群机器人) 与 HMAC 签名安全配置
    connector_hmac_secret: str = Field(default="")
    connector_http_timeout_seconds: float = Field(default=5.0)
    connector_max_retries: int = Field(default=3)

    # 净室子进程沙箱操作系统级资源限制
    sandbox_max_memory_mb: int = Field(default=256)
    sandbox_max_output_bytes: int = Field(default=65536)

    # Secure by default; False is an explicit local-demo compatibility mode.
    enforce_bearer_auth: bool = Field(default=True)
    bootstrap_password: str = Field(default="")

    @property
    def has_live_llm(self) -> bool:
        key = self.llm_api_key.strip()
        return bool(key and not key.startswith("your_") and key != "mock")


def load_settings(**overrides) -> ArachneSettings:
    explicit_key_passed = "llm_api_key" in overrides
    settings = ArachneSettings(**overrides)
    if explicit_key_passed:
        settings.llm_api_key = str(overrides["llm_api_key"] or "").strip()
        return settings

    if not settings.has_live_llm:
        env_key = os.environ.get("LLM_API_KEY", "").strip()
        if env_key and not env_key.startswith("your_") and env_key != "mock":
            settings.llm_api_key = env_key
        else:
            try:
                keychain_key = subprocess.check_output(
                    ["security", "find-generic-password", "-s", "deepseek-api-key", "-w"],
                    text=True,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                ).strip()
                if keychain_key:
                    settings.llm_api_key = keychain_key
            except Exception:
                pass

    if "connector_hmac_secret" not in overrides and os.environ.get("ARACHNE_CONNECTOR_HMAC_SECRET"):
        settings.connector_hmac_secret = os.environ["ARACHNE_CONNECTOR_HMAC_SECRET"].strip()
    if "connector_http_timeout_seconds" not in overrides and os.environ.get("ARACHNE_CONNECTOR_HTTP_TIMEOUT_SECONDS"):
        settings.connector_http_timeout_seconds = float(os.environ["ARACHNE_CONNECTOR_HTTP_TIMEOUT_SECONDS"])
    if "connector_max_retries" not in overrides and os.environ.get("ARACHNE_CONNECTOR_MAX_RETRIES"):
        settings.connector_max_retries = int(os.environ["ARACHNE_CONNECTOR_MAX_RETRIES"])
    if "sandbox_max_memory_mb" not in overrides and os.environ.get("ARACHNE_SANDBOX_MAX_MEMORY_MB"):
        settings.sandbox_max_memory_mb = int(os.environ["ARACHNE_SANDBOX_MAX_MEMORY_MB"])
    if "sandbox_max_output_bytes" not in overrides and os.environ.get("ARACHNE_SANDBOX_MAX_OUTPUT_BYTES"):
        settings.sandbox_max_output_bytes = int(os.environ["ARACHNE_SANDBOX_MAX_OUTPUT_BYTES"])
    if "enforce_bearer_auth" not in overrides and os.environ.get("ARACHNE_ENFORCE_BEARER_AUTH"):
        raw_enforce = os.environ["ARACHNE_ENFORCE_BEARER_AUTH"].strip().lower()
        settings.enforce_bearer_auth = raw_enforce in ("1", "true", "yes", "on")
    return settings


