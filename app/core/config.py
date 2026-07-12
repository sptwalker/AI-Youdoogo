"""应用统一配置入口：所有环境变量经由 Settings 读取，禁止散落 os.getenv。"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "change-me-in-phase-1"


class Settings(BaseSettings):
    """全局配置（字段与 .env.example 一一对应）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    app_env: str = "local"
    log_level: str = "INFO"
    api_port: int = 8000
    jwt_secret: str = _DEFAULT_JWT_SECRET  # 仅 local 可用默认值，非 local 启动即校验
    jwt_expire_minutes: int = 720  # 访问令牌有效期（分钟），首版12小时免刷新负担

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

    # LLM 用量：当日 token 预算，超阈值告警（0=不启用）
    llm_daily_token_budget: int = 0

    # 飞书
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_notify_enabled: bool = False
    feishu_ops_chat_id: str = ""  # 运营通知群 chat_id（日报/告警推送目标）

    # ThinkingData 运营数据平台（docs/11 附录B）
    td_base_url: str = ""  # 形如 http://HOST:8992，待联调确认
    td_api_secret: str = ""

    @model_validator(mode="after")
    def _enforce_prod_secret(self) -> "Settings":
        """非 local 环境拒绝弱/默认 JWT 密钥，启动即失败而非静默签发可伪造令牌。"""
        if self.app_env != "local" and (
            self.jwt_secret == _DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError(
                "生产环境 JWT_SECRET 必须覆盖默认值且长度≥32；"
                '可用 python -c "import secrets;print(secrets.token_urlsafe(48))" 生成'
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """进程级单例。"""
    return Settings()
