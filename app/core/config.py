"""应用统一配置入口：所有环境变量经由 Settings 读取，禁止散落 os.getenv。"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置（字段与 .env.example 一一对应）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    app_env: str = "local"
    log_level: str = "INFO"
    api_port: int = 8000
    jwt_secret: str = "change-me-in-phase-1"

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/youdoo"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "youdoo"

    # 大模型密钥（国产为主，DeepSeek 主力）
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    zhipu_api_key: str = ""
    anthropic_api_key: str = ""

    # 飞书
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_notify_enabled: bool = False


@lru_cache
def get_settings() -> Settings:
    """进程级单例。"""
    return Settings()
