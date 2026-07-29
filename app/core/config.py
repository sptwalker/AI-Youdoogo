"""应用统一配置入口：所有环境变量经由 Settings 读取，禁止散落 os.getenv。"""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "local-only-jwt-secret-change-in-production"


class Settings(BaseSettings):
    """全局配置（字段与 .env.example 一一对应）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 应用
    app_env: str = "local"
    log_level: str = "INFO"
    api_port: int = 8000
    jwt_secret: str = _DEFAULT_JWT_SECRET  # 仅 local 可用默认值，非 local 启动即校验
    jwt_expire_minutes: int = 720  # 访问令牌有效期（分钟），首版12小时免刷新负担
    # 应用密钥：派生 Fernet 加密密钥，加密存库的敏感字段（AI 卡片 api_key 等，H1.1）。
    # 留空则回退 jwt_secret 派生；生产建议单独设置，与 jwt_secret 分离。
    app_secret_key: str = ""

    # Internal JWT（服务间鉴权，C1 / docs/21 §9）：非对称 ES256 短期服务身份 token，与用户 HS256
    # jwt_secret 彻底隔离——「不共享业务 JWT_SECRET」（§9 L1414）。留空=不签发（本地无出站时正常）；
    # Phase 1 RemoteLlmAdapter 上线时此项转生产必填。私钥禁入库，只经 .env/Settings。
    internal_jwt_private_key: str = ""  # ES256 私钥 PEM（签发用），见 .env.example 生成命令
    internal_jwt_public_key: str = ""  # ES256 公钥 PEM（验签用）；留空则从私钥派生（自签自验）
    internal_jwt_issuer: str = "youdoogo-platform"  # 本服务签发的 iss
    internal_jwt_expire_seconds: int = 300  # 服务 token 有效期（秒），文档硬上限 exp≤5min

    # 数据库
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/youdoo"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "youdoo"
    minio_secure: bool = False  # 生产置 True 走 TLS；本地/compose MinIO 明文默认 False

    # 大模型密钥（国产为主，DeepSeek 主力）
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    zhipu_api_key: str = ""
    anthropic_api_key: str = ""

    # LLM 用量：当日 token 预算，超阈值告警（0=不启用）
    llm_daily_token_budget: int = 0
    # 预算硬闸（H2.2）：True 时超预算直接拒绝新 LLM 调用（默认 False=仅告警不拒绝）
    llm_budget_hard_limit: bool = False
    # LLM 调用护栏（H2.1）：单次请求超时、SDK 重试、failover 尝试上限、总超时封顶
    llm_request_timeout: float = 60.0  # 单候选单次请求超时（秒）
    llm_max_retries: int = 1  # 单候选 SDK 层重试次数（有 failover，不必多）
    llm_failover_max_attempts: int = 3  # failover 最多尝试候选数（0=不限）
    llm_total_timeout: float = 120.0  # 整条 failover 链总墙钟预算（秒，0=不限）

    # LLM Gateway 远程切换（Phase 1 / docs/21）：Branch-by-Abstraction 整体开关。
    # mode=remote 且 url 非空 → RemoteLlmAdapter；否则回退 Local（默认 local，无服务时安全）。
    llm_completion_mode: str = "local"  # local | remote
    llm_gateway_url: str = ""  # 网关根地址（形如 http://ai-model-gateway:8080）；空=未部署
    llm_gateway_max_retries: int = 2  # 连接错误/5xx 有界重试次数（超时复用 llm_request_timeout）

    # Durable workflow worker（PostgreSQL outbox + 租约）
    workflow_worker_enabled: bool = True
    workflow_worker_poll_seconds: float = 1.0
    workflow_event_lease_seconds: int = 300
    workflow_step_lease_seconds: int = 600
    workflow_retry_delay_seconds: int = 5
    workflow_recovery_scan_seconds: float = 30.0
    workflow_recovery_batch_size: int = 100

    # Embedding（知识库向量化，A/B 可配置：留空则用通义 text-embedding-v3）
    embedding_base_url: str = ""  # OpenAI 兼容 /embeddings 端点根地址；留空→通义
    embedding_model: str = "text-embedding-v3"  # 换 bge-m3 等在此改（需 1024 维）
    embedding_api_key: str = ""  # 留空则回退 dashscope_api_key

    # 飞书
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_oauth_enabled: bool = False
    feishu_redirect_url: str = ""
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

    @model_validator(mode="after")
    def _enforce_internal_jwt(self) -> "Settings":
        """Internal JWT 约束：exp≤5min（文档硬上限）；配了私钥则须能解析为 EC 私钥（启动即校验）。

        私钥留空允许（本地无出站时不签发）；Phase 1 RemoteLlmAdapter 上线时另在其任务转生产必填。
        """
        if not (1 <= self.internal_jwt_expire_seconds <= 300):
            raise ValueError("INTERNAL_JWT_EXPIRE_SECONDS 必须在 1..300（文档硬上限 exp≤5min）")
        if self.internal_jwt_private_key:
            # 尽早校验 PEM 合法，避免运行时首次签发才 500；仅在配了私钥时校验。
            from cryptography.hazmat.primitives.asymmetric import ec
            from cryptography.hazmat.primitives.serialization import load_pem_private_key

            try:
                key = load_pem_private_key(self.internal_jwt_private_key.encode(), password=None)
            except (ValueError, TypeError) as exc:
                raise ValueError("INTERNAL_JWT_PRIVATE_KEY 不是合法 PEM 私钥") from exc
            if not isinstance(key, ec.EllipticCurvePrivateKey):
                raise ValueError("INTERNAL_JWT_PRIVATE_KEY 必须是 EC（ES256）私钥，而非 RSA/其它")
        return self

    @model_validator(mode="after")
    def _enforce_llm_gateway(self) -> "Settings":
        """切远程模式必须配网关地址：启动即失败，而非运行时首个 LLM 调用才 500。"""
        if self.llm_completion_mode not in ("local", "remote"):
            raise ValueError("LLM_COMPLETION_MODE 必须是 local 或 remote")
        if self.llm_completion_mode == "remote" and not self.llm_gateway_url:
            raise ValueError("LLM_COMPLETION_MODE=remote 时必须配置 LLM_GATEWAY_URL")
        return self


@lru_cache
def get_settings() -> Settings:
    """进程级单例。"""
    return Settings()
