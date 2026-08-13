"""应用统一配置入口：所有环境变量经由 Settings 读取，禁止散落 os.getenv。"""

from functools import lru_cache
from urllib.parse import unquote, urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "local-only-jwt-secret-change-in-production"
_MAX_LODGE_HTTP_TIMEOUT_SECONDS = 30.0
_MAX_LODGE_JWKS_CACHE_TTL_SECONDS = 3_600
_MAX_LODGE_STATUS_CACHE_TTL_SECONDS = 300
_MAX_LODGE_RESPONSE_BYTES = 1_048_576


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
    # 迁移期对象存储能力。secure=False 保持现有本地 MinIO 行为；生产切换 TLS
    # 时只需改变配置，不改变 gateway 的旧 put/get API。
    minio_secure: bool = False
    # 逗号分隔的资源权限 allowlist。空 bucket 列表仅允许 minio_bucket，空 prefix
    # 列表表示当前 bucket 下保持兼容的全路径访问。
    minio_allowed_buckets: str = ""
    minio_allowed_prefixes: str = ""
    minio_presign_expire_seconds: int = 900

    # 跨服务身份（默认关闭，不影响用户 JWT 或当前部署拓扑）。私钥只从配置读取，
    # 不在应用内生成，也不在仓库保存。平台 service_identity 使用 RS256；旧的
    # app.core.internal_token 使用 ES256。两套实现迁移期间共存，但不能混用启用路径。
    internal_jwt_enabled: bool = False
    internal_jwt_audience: str = ""
    internal_jwt_service_id: str = ""
    internal_jwt_ttl_seconds: int = 300

    # Lodge resource-server（默认关闭；独立于现有 HS256 用户登录）。仅验证 Lodge
    # 发给 youdoogo 的浏览器 target token，绝不将该 token 转发给下游服务。
    lodge_identity_enabled: bool = False
    lodge_issuer: str = ""
    lodge_jwks_url: str = ""
    lodge_audience: str = "youdoogo"
    lodge_status_url: str = ""
    lodge_status_service_token: SecretStr = SecretStr("")
    lodge_http_timeout_seconds: float = 3.0
    lodge_jwks_cache_ttl_seconds: int = 300
    lodge_status_cache_ttl_seconds: int = 60
    lodge_status_cache_max_entries: int = 10_000
    lodge_response_max_bytes: int = 65_536

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
    llm_gateway_canary_percent: int = 0  # remote 灰度百分比 0–100（docs/21 步骤5）：
    # 0=全 local（默认，生产安全）；100=全 remote（等价整体开关）；0<p<100=按调用抽样 canary。

    # Knowledge Service 远程切换（Phase 2 / docs/21 §11「先切只读 Search」）：Branch by Abstraction
    # mode=remote 且 url 非空 → RemoteKnowledgeSearchAdapter；否则回退 Local（默认 local，安全）。
    knowledge_search_mode: str = "local"  # local | remote
    knowledge_gateway_url: str = ""  # 知识服务根地址（http://ai-knowledge-service:8080）；空=未部署
    knowledge_gateway_timeout: float = 30.0  # 单次检索请求超时（秒）
    knowledge_gateway_max_retries: int = 2  # 连接错误/5xx 有界重试（Search 幂等只读，可安全重试）
    knowledge_gateway_canary_percent: int = 0  # remote 灰度百分比 0–100（同 LLM canary 语义）
    # 写侧（索引）开关：复用同一 knowledge_gateway_url。写是副作用，不能按调用随机
    # 抽样（会分裂写真源，违 docs/21 禁双写红线）——只做硬 local|remote 切换，无 canary。
    knowledge_index_mode: str = "local"  # local | remote

    # Expert Platform 远程切换（Phase 3 / docs/23 §6.2 第一场景）：Branch by Abstraction。
    # 缝设在既有 LlmCompletionPort——mode=remote 且 url 非空 → RemoteExpertExecutionAdapter
    # （远程为主、本地兜底）；否则回退 build_llm_completion_port（默认 local，无服务时逐字不变）。
    expert_execution_mode: str = "local"  # local | remote
    expert_platform_url: str = ""  # 专家平台根地址（http://ai-expert-platform:8080）；空=未部署
    expert_platform_timeout: float = 60.0  # 单次请求超时（秒）
    expert_platform_max_retries: int = 2  # 连接错误/5xx 有界重试（创建幂等，可安全重试）
    expert_platform_canary_percent: int = 0  # remote 灰度百分比 0–100（同 LLM canary 语义）
    # 真·网关执行器转发开关（docs/23 §6.4）：on → _create_remote mint gateway_token（aud=
    # ai-model-gateway, scope=llm:complete）随体转发，远端 GatewayExecutor Bearer 中继跑真模型；
    # off（默认）→ 不 mint、body 无令牌 → 远端回落 echo。开启须配 internal_jwt_private_key。
    expert_forward_gateway_token: bool = False

    # 同步 Capability Provider 服务面（docs/23 §6.7）：on → 挂 POST /internal/capabilities/execute
    # （服务身份 + capabilities:execute scope，只放行 SYNC_LOCAL 能力，复用全链执行）。默认关 →
    # 路由不注册 → 生产逐字不变、零新入站攻击面。验签走 internal_jwt_public_key（调用方持私钥）。
    capability_provider_enabled: bool = False

    # 远端 expert 工具调用环（docs/23 §6.8）：youdoo 自身对 expert 可达的根地址。非空 → rich sync 时
    # mint capabilities_token（aud=self issuer, scope=capabilities:execute）+ 追加工具广告随体转发，
    # 远端 ToolLoopExecutor 让模型多轮回调本端点取数。空（默认）→ 不 mint、不广告 → 远端透传不循环。
    # 端到端还需本端开 capability_provider_enabled（接收回调）+ Internal JWT 密钥。
    capability_callback_url: str = ""  # 如 http://ai-youdoogo:8000；空=工具环关，生产逐字不变

    # 事件传输门禁（Phase 3 硬前置 / docs/21 §Immediate Backlog C + docs/23）：出站 HTTP Relay
    # 把 outbox 事件投递给对端 Inbox。默认关 → 现网 worker 行为零改变；开关 on → 装配 HttpInboxRelay
    # 并 register_event_handler；缺 peer/私钥则启动即失败（fail-fast，见 _enforce_event_relay）。
    event_relay_enabled: bool = False  # 出站总开关
    # 入站门（docs/23 §3.3）：on 才挂 /internal/events，默认关=零新入站面。与出站正交；
    # 回环自验/收对端事件需 on，否则 relay 投递打到未挂载端点 → 404 → DLQ。
    event_inbox_enabled: bool = False
    event_inbox_peer_url: str = ""  # 对端 inbox 根地址（回环验证填自身，如 http://localhost:8000）
    event_inbox_peer_audience: str = ""  # 对端 inbox 期望的 aud（空=回退本服务 issuer 走回环自验；
    # 跨仓填对端 service_id 如 ai-expert-platform，使 transport 令牌可被对端验签）
    event_relay_event_types: tuple[str, ...] = ()  # 允许中继的事件类型 allowlist（空=不中继任何）
    # 后台步骤异步远端执行（docs/23 §6.3）：skill ∈ allowlist 的 ready step
    # 出站给 expert 并停车，其余走本地 execute（默认空=全本地，逐字不变）。
    # 停车 = sentinel-owner + 长租约；过期即本地重跑降级。
    event_remote_step_skills: tuple[str, ...] = ()  # 远端异步 skill allowlist（空=全本地）
    event_remote_step_lease_seconds: int = 3600  # 停车长租约秒（echo 往返 <1s；过期即降级）

    # Workflow 执行引擎选择（docs/24 §4 / docs/21 Phase4 step6）：新建 run 创建期固定盖此戳
    # （workflow_run.engine，之后不可改写，避免双真源）。database=自研 DAG runtime（默认）；
    # 接远程 Runtime/LangGraph 时改此默认或按 workflow_type 传参。未知引擎名 fail-closed 拒绝。
    workflow_engine: str = "database"

    # Durable workflow worker（PostgreSQL outbox + 租约）
    workflow_worker_enabled: bool = True
    workflow_worker_poll_seconds: float = 1.0
    workflow_event_lease_seconds: int = 300
    workflow_step_lease_seconds: int = 600
    workflow_retry_delay_seconds: int = 5
    workflow_recovery_scan_seconds: float = 30.0
    workflow_recovery_batch_size: int = 100

    # 定时报告调度（docs/25 P1-1）：复用 workflow worker 循环的时钟闸做「到点扫描 due 的
    # report_schedule」，不引入 celery/apscheduler。默认关 + 种子行默认停用 + creator_id 为空即
    # 跳过 = 三重保险，生产逐字不变。系统自动发起的 run 仍走 plan_work → start_workflow
    # （同一 is_red_line 判定），对外/资金/人事/发布步骤前必停 waiting_human。
    report_scheduler_enabled: bool = False
    report_schedule_scan_seconds: float = 300.0

    # 营销舆情事件驱动响应（docs/26 P2）：注册 sentiment.anomaly.detected 的 outbox handler，
    # 命中即经 report_scheduler._start_workflow 系统发起应急响应 workflow（同一 is_red_line，
    # feishu_notify_person 等对外步骤前必停 waiting_human）。默认关——注册与否自门控，红线不旁路。
    sentiment_response_enabled: bool = False

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
        if self.lodge_identity_enabled:
            required = {
                "LODGE_ISSUER": self.lodge_issuer,
                "LODGE_JWKS_URL": self.lodge_jwks_url,
                "LODGE_STATUS_URL": self.lodge_status_url,
                "LODGE_STATUS_SERVICE_TOKEN": self.lodge_status_service_token.get_secret_value(),
            }
            missing = [name for name, value in required.items() if not value.strip()]
            if missing:
                raise ValueError(f"Lodge enabled but missing: {', '.join(missing)}")
            if self.lodge_audience != "youdoogo":
                raise ValueError("LODGE_AUDIENCE must be exactly youdoogo")
            _validate_lodge_url(self.lodge_issuer, "LODGE_ISSUER")
            _validate_lodge_url(self.lodge_jwks_url, "LODGE_JWKS_URL", require_path=True)
            _validate_lodge_url(self.lodge_status_url, "LODGE_STATUS_URL", require_path=True)
            if not 0 < self.lodge_http_timeout_seconds <= _MAX_LODGE_HTTP_TIMEOUT_SECONDS:
                raise ValueError("LODGE_HTTP_TIMEOUT_SECONDS must be between 0 and 30")
            if not 0 < self.lodge_jwks_cache_ttl_seconds <= _MAX_LODGE_JWKS_CACHE_TTL_SECONDS:
                raise ValueError("LODGE_JWKS_CACHE_TTL_SECONDS must be between 1 and 3600")
            if not 0 < self.lodge_status_cache_ttl_seconds <= _MAX_LODGE_STATUS_CACHE_TTL_SECONDS:
                raise ValueError("LODGE_STATUS_CACHE_TTL_SECONDS must be between 1 and 300")
            if self.lodge_status_cache_max_entries <= 0:
                raise ValueError("LODGE_STATUS_CACHE_MAX_ENTRIES must be greater than zero")
            if not 0 < self.lodge_response_max_bytes <= _MAX_LODGE_RESPONSE_BYTES:
                raise ValueError("LODGE_RESPONSE_MAX_BYTES must be between 1 and 1048576")
        return self

    @model_validator(mode="after")
    def _enforce_internal_jwt(self) -> "Settings":
        """Validate both internal-token generations during the migration window.

        ``internal_jwt_enabled`` selects the new RS256 service-identity component,
        which performs its own RSA validation.  With the flag disabled, existing
        remote adapters continue to use the legacy ES256 token implementation.
        """
        if not (1 <= self.internal_jwt_expire_seconds <= 300):
            raise ValueError("INTERNAL_JWT_EXPIRE_SECONDS 必须在 1..300（文档硬上限 exp≤5min）")
        if not (1 <= self.internal_jwt_ttl_seconds <= 300):
            raise ValueError("INTERNAL_JWT_TTL_SECONDS must be between 1 and 300")
        if self.internal_jwt_private_key and not self.internal_jwt_enabled:
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
        if not 0 <= self.llm_gateway_canary_percent <= 100:
            raise ValueError("LLM_GATEWAY_CANARY_PERCENT 必须在 0–100 之间")
        return self

    @model_validator(mode="after")
    def _enforce_expert_platform(self) -> "Settings":
        """切远程专家平台必须配 url + 私钥：启动即失败，而非运行时首个执行才 500。"""
        if self.expert_execution_mode not in ("local", "remote"):
            raise ValueError("EXPERT_EXECUTION_MODE 必须是 local 或 remote")
        if self.expert_execution_mode == "remote":
            if not self.expert_platform_url:
                raise ValueError("EXPERT_EXECUTION_MODE=remote 时必须配置 EXPERT_PLATFORM_URL")
            if not self.internal_jwt_private_key:
                raise ValueError("EXPERT_EXECUTION_MODE=remote 时必须配置 INTERNAL_JWT_PRIVATE_KEY")
        if not 0 <= self.expert_platform_canary_percent <= 100:
            raise ValueError("EXPERT_PLATFORM_CANARY_PERCENT 必须在 0–100 之间")
        return self

    @model_validator(mode="after")
    def _enforce_knowledge_gateway(self) -> "Settings":
        """切远程知识检索必须配服务地址：启动即失败，而非运行时首个检索才 500（同 LLM 网关）。"""
        if self.knowledge_search_mode not in ("local", "remote"):
            raise ValueError("KNOWLEDGE_SEARCH_MODE 必须是 local 或 remote")
        if self.knowledge_search_mode == "remote" and not self.knowledge_gateway_url:
            raise ValueError("KNOWLEDGE_SEARCH_MODE=remote 时必须配置 KNOWLEDGE_GATEWAY_URL")
        if not 0 <= self.knowledge_gateway_canary_percent <= 100:
            raise ValueError("KNOWLEDGE_GATEWAY_CANARY_PERCENT 必须在 0–100 之间")
        if self.knowledge_index_mode not in ("local", "remote"):
            raise ValueError("KNOWLEDGE_INDEX_MODE 必须是 local 或 remote")
        if self.knowledge_index_mode == "remote" and not self.knowledge_gateway_url:
            raise ValueError("KNOWLEDGE_INDEX_MODE=remote 时必须配置 KNOWLEDGE_GATEWAY_URL")
        return self


    @model_validator(mode="after")
    def _enforce_event_relay(self) -> "Settings":
        """开事件中继必须配对端地址 + 私钥：启动即失败，而非运行时首个事件投递才 500。

        中继需签发服务令牌（走 internal_jwt_private_key），故开关 on 时私钥也必填。
        """
        if self.event_relay_enabled:
            if not self.event_inbox_peer_url:
                raise ValueError("EVENT_RELAY_ENABLED=true 时必须配置 EVENT_INBOX_PEER_URL")
            if not self.internal_jwt_private_key:
                raise ValueError(
                    "EVENT_RELAY_ENABLED=true 时必须配置 INTERNAL_JWT_PRIVATE_KEY（中继需签发令牌）"
                )
        if self.event_remote_step_skills and not self.event_relay_enabled:
            raise ValueError(
                "EVENT_REMOTE_STEP_SKILLS 非空时必须开 EVENT_RELAY_ENABLED（远端步骤经 relay 出站）"
            )
        return self

    @model_validator(mode="after")
    def _enforce_capability_callback(self) -> "Settings":
        """配了工具回调地址必开 Provider：否则 expert 回调打到未挂载端点→404→工具环静默失效。

        fail-fast 于启动，而非运行时首个工具回调才断（对称于 _enforce_event_relay 的出站前置）。
        """
        if self.capability_callback_url and not self.capability_provider_enabled:
            raise ValueError(
                "CAPABILITY_CALLBACK_URL 非空时必须开 CAPABILITY_PROVIDER_ENABLED"
                "（回调打回本端 /internal/capabilities/execute，Provider 关则 404）"
            )
        return self


def _validate_lodge_url(raw_url: str, setting_name: str, *, require_path: bool = False) -> None:
    """Reject ambiguous remote endpoints before a client can be constructed."""
    try:
        parsed = urlsplit(raw_url)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{setting_name} must be a valid HTTPS URL") from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
    ):
        raise ValueError(
            f"{setting_name} must be a fixed HTTPS URL without userinfo, query, or fragment"
        )
    if require_path and not _is_safe_fixed_path(parsed.path):
        raise ValueError(f"{setting_name} must include a safe, non-root path")


def _is_safe_fixed_path(path: str) -> bool:
    decoded_path = unquote(path)
    if not decoded_path.startswith("/") or decoded_path.rstrip("/") == "" or "//" in decoded_path:
        return False
    return all(segment not in {".", ".."} for segment in decoded_path.split("/") if segment)


@lru_cache
def get_settings() -> Settings:
    """进程级单例。"""
    return Settings()
