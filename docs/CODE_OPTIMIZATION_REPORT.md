# 代码优化与重构分析报告

**生成时间**: 2026-07-28
**项目**: 创想悦动AI决策大脑系统
**对比基线**: `gitlab/dev@10bb9fc`，679个生产Python文件，46,990行代码
**当前代码规模**: 641个生产Python文件，45,490行代码（-38文件，-1,500行）

## 一、整体评估

### 1.1 代码规模分布

```
总目录数: 401个
总文件数: 641个生产Python文件
总代码行: 45,490行

核心模块分布:
- app/contexts/     14MB (占93%)  - 业务上下文层
- app/api/          360KB         - HTTP路由层（迁移期）
- app/platform/     248KB         - 技术平台层
- app/models/       220KB         - ORM模型（迁移期）
- app/agents/       128KB         - 智能体运行时
- app/integrations/ 124KB         - 第三方集成
- app/llm/          104KB         - LLM网关
- app/schemas/      88KB          - HTTP DTO（迁移期）
- app/core/         88KB          - 配置与安全
```

### 1.2 架构健康度

| 维度 | 状态 | 说明 |
|-----|------|------|
| DDD分层 | ✅ 良好 | 33个Application层、33个Infrastructure层、21个Domain层 |
| 类数量 | ⚠️ 偏多 | 1070个类（平均每文件1.7个） |
| 函数数量 | ⚠️ 偏多 | 407个同步函数 + 499个异步函数 |
| 内部依赖 | ⚠️ 复杂 | 1422处内部import |
| 旧代码耦合 | ⚠️ 存在 | 74处contexts对app.models的依赖 |

---

## 二、发现的主要问题

### 2.1 超大文件问题（Top 10）

| 文件 | 行数 | 问题 |
|-----|------|------|
| `group_messaging/application/use_cases.py` | 501 | 单个Application类承载过多职责 |
| `assistant_conversations/application/use_cases.py` | 455 | 会话编排逻辑过度集中 |
| `organization_structure/application/use_cases.py` | 405 | 组织树操作未按命令拆分 |
| `meeting_management/application/use_cases.py` | 402 | 会议全生命周期耦合 |
| `collaboration_requests/entrypoints/agent_capability.py` | 386 | 智能体能力暴露未分层 |
| `knowledge/knowledge_indexing/infrastructure/sqlalchemy_index.py` | 381 | 索引实现过重 |
| `feishu/client.py` | 364 | 飞书客户端单体化 |
| `assistant_conversations/infrastructure/adapters.py` | 358 | 适配器职责混杂 |
| `governed_data_query/entrypoints/agent_capability.py` | 329 | 数据查询能力未模块化 |
| `service_identity/jwt.py` | 319 | JWT实现过于底层 |

**建议**: 单文件超过300行应考虑拆分，Application类超过200行应按CQRS拆分Command/Query。

---

### 2.2 职责过重的Application类（预估，等后台任务完成）

根据文件大小推断可能存在"God Class"：

- `GroupMessagingApplication`: 501行，管理频道+消息+附件+实时推送+AI回复
- `AssistantConversationsApplication`: 455行，管理会话+消息+编排+归档+附件
- `OrganizationApplication`: 405行，组织树CRUD+权限+飞书同步
- `MeetingApplication`: 402行，会议创建+议程+纪要+AI总结+任务转化

**建议**:
1. 按聚合根拆分：如`ChannelLifecycleService` + `MessageStreamService`
2. 按用例类型拆分：如`ProposalCommands` + `ProposalQueries`

---

### 2.3 迁移期兼容层残留（已验证）

contexts 对迁移期兼容层的 import 统计（`grep -rE "from app\.<layer>" app/contexts`）：

| 兼容层 | 被 contexts 引用次数 | 备注 |
|-------|-----|------|
| `app.models` | 74 | 集中在各 Context 的 infrastructure 适配器（ORM 表复用） |
| `app.core` | 25 | 主要是 config/database 兼容入口 |
| `app.agents` | 18 | Agent runtime 兼容入口 |
| `app.llm` | 16 | LLM gateway 兼容入口 |
| `app.integrations` | 11 | 飞书 client |
| `app.schemas` | 1 | 基本已退出 |

引用 `app.models` 最多的文件（每文件 2~3 处）：
- `foundations/governance/ai_quality/infrastructure/sqlalchemy_adapter.py`
- `business/work_desktop/infrastructure/adapters.py`
- `foundations/knowledge/wiki_management/infrastructure/{visibility,sqlalchemy}.py`
- `business/task_management/infrastructure/sqlalchemy_adapter.py` 等

**说明**: 这些引用集中在 infrastructure 层，属于 docs/20 第11节规划中的迁移期共享 ORM 表，
不是 route/application 层违规（架构门禁当前通过，ruff 全绿）。但它们是"ORM 表所有权还没
下沉到 Context"的标志——每消除一处，对应 Context 才真正自治，`app/models/`（220KB）才能删除。

**修复路径**:
1. 按 docs/20 的 ownership map，把各表的 ORM 定义移入唯一 owner Context 的 infrastructure
2. 其他 Context 需要该数据时走对方 public.py 契约，不共享表
3. 全部下沉后删除 `app/models/` 兼容层（约5,000+行）

---

### 2.4 已验证的重复代码（逐文件核实，非推测）

#### (a) 附件链路 —— 真正的复制粘贴事故（最优先处理）

assistant_conversations 与 group_messaging 两个 Context 的整条附件链路是复制粘贴的产物
（证据：`_IMAGE_EXTENSIONS` 在两个 use_cases.py 都恰好落在第 58 行，错误文案一字不差）：

| 重复项 | 位置 |
|---|---|
| `_IMAGE_EXTENSIONS` 常量（逐字相同） | 两个 `use_cases.py:58` |
| 20MB 上限常量 | assistant_conversations `use_cases.py:57`、group_messaging `contracts.py:11`（命名/归属层不同，值与用途相同） |
| `upload_attachment` 方法体（逻辑同构） | assistant_conversations `use_cases.py:148-171`、group_messaging `use_cases.py:280-294`，唯一实质差异是 object 前缀 `desktop-chat/` vs `chat/` |
| `download_attachment` 方法体（同构） | `use_cases.py:173-191` vs `use_cases.py:296-310`，含相同的 `InvalidInput("非法附件路径")`、`PermissionDenied("无权访问该附件")` 文案 |
| `AttachmentResult`/`AttachmentDownloadResult` DTO（逐字相同，含 `as_dict`） | 两个 `contracts.py` |
| `AttachmentStoragePort` Protocol（逐字相同） | 两个 `ports.py:107-110`（连行号都相同） |
| `KnowledgeAttachmentStorageAdapter`（字节级相同） | assistant_conversations `adapters.py:325-330`、group_messaging `adapters.py:155-160` |
| API 层 upload/download handler（结构一致，`Content-Disposition` 行逐字相同） | `app/api/v1/discussion.py:29-60`、`app/api/v1/desktop.py:112-147` |

#### (b) 技术性 Port 协议与实现的重复

- `Clock(Protocol)`：**8 处逐字重复** + 3 个换名版本（`ClockPort`/`ExecutionClock`/`UsageClockPort`），合计 11 处
- `IdentifierPort(Protocol)`：**9 处**（含 `new_id()`），另有 `TaskIdentifierPort` 别名；`new_object_token` 在 3 处重复
- `SystemClock` 实现类：**10 处**，全部是 `return datetime.now(UTC)` 一行
- `UUIDIdentifier` 实现类：**11 处**，核心都是 `return uuid.uuid4()`
- UnitOfWork Protocol 四件套（`__aenter__/__aexit__/commit/rollback`）：**15 处** 逐字样板，每处约 12 行
- `AuditPort` + `AuditRequest`：2 处完全相同（collaboration_requests、proposal_management）
- `ExpertSnapshotPort`：2 处逐字相同（agent_execution、workflow_runtime）

**重要辨析**：以下是**同名不同契约**的命名冲突，不是重复，不可合并——
`ConversationArchivePort`（request 类型不同）、`IdentityDirectoryPort`（`get()` vs `user_exists()`）、
`AgentExecutionPort`（方法集不同）。

#### (c) 不是重复的项（排除误报）

- `deduplicate_mentions` vs `deduplicate_added_agents`：语义不同（前者按 MAX_FANOUT 截断，后者排除 assistant 自身并抛错），各只有一处实现，**不是重复**
- 分页逻辑：全库仅 4 处 `.limit(`、0 处 `.offset(`，**不存在分页模板重复**
- infrastructure 的 19 个 row→domain 映射函数：各 aggregate 字段不重叠，属于"同模式不同数据"，**不建议合并**，只有命名风格（`_to_domain`/`xxx_to_domain`/`_xxx_from_row` 三种）值得统一

#### (d) 结构性冗余（消除需要改分层策略，非机械重构）

meeting_management 中 `sqlalchemy_repository.py` 的 4 个 `_from_row` 与 application 层的
4 个 `_xxx_result` 形成一对一影子映射——同一批字段搬两次（row→domain→result）。这是真正的
结构性冗余，但消除它要改变分层策略，应作为独立决策，不混入机械去重。

#### (e) 机械可消除行数合计（实测口径）

按副本数 × 行数核算，纯机械去重约 **300~390 行**。这个数字远小于直觉——说明这个库的
"乱"主要不在复制粘贴，而在**超大类、模板样板和迁移期兼容层**（见 2.1/2.3 与 7.1）。

**架构辨析**：(b) 类 Port 重复很可能是刻意的 DDD 选择——每个 Context 自持 ports.py 换取独立
演化，Protocol 是结构化类型，重复成本只有几行。合并到 shared_kernel 会让 14 个 Context 共享
一个变更点，需要先在 docs/20 层面做出决策。相比之下 (a) 附件链路是明确的事故，无争议可修。

---

### 2.5 基础设施层膨胀

| 模块 | 问题 |
|-----|------|
| `app/llm/factory.py` (288行) | 模型工厂逻辑过重 |
| `app/llm/fallback.py` (276行) | Failover逻辑可抽象 |
| `app/integrations/feishu/client.py` (364行) | 未按资源类型拆分 |
| 各种`adapters.py` (69个文件) | 适配器过多但未标准化 |

**建议**:
- LLM层: 分离工厂/健康检查/验证/failover到独立模块
- 飞书集成: 按资源拆分 `FeishuAuth/FeishuUser/FeishuMessage/FeishuContact`
- 适配器: 定义标准Port接口，减少定制化适配器

---

## 三、优化建议（优先级排序）

### P0 - 架构治理（清除技术债）

#### 3.1 完成旧代码退出（2-3天）
**目标**: 彻底移除`app.models`、`app.schemas`、`app.services`对contexts的污染

```python
# 当前状态
app.contexts → app.models  # 74处违规依赖

# 目标状态
app.contexts 完全自治
app.bootstrap 完成组装和映射
```

**具体步骤**:
1. 为每个Context定义自己的持久化模型（可复用SQLAlchemy Table，但属于Context）
2. Repository实现移到Context/infrastructure内
3. 清理所有`from app.models import`
4. 验证架构门禁通过

#### 3.2 标准化UnitOfWork模式（1-2天）
**目标**: 消除直接数据库会话依赖

```python
# 当前反模式
@router.post("/xxx")
async def endpoint(db: AsyncSession = Depends(get_db)):
    # 直接操作db

# 目标模式
@router.post("/xxx")
async def endpoint(app: XxxApplication = Depends(get_xxx_app)):
    result = await app.execute_command(...)
```

**收益**:
- 测试时可替换为内存UoW
- 清晰的事务边界
- 解耦HTTP层与持久化层

---

### P1 - 代码压缩（减少30%+代码量）

#### 3.3 拆分超大Application类（3-5天）

**目标文件** (选4个最大的先处理):
1. `group_messaging/application/use_cases.py` (501行)
2. `assistant_conversations/application/use_cases.py` (455行)
3. `organization_structure/application/use_cases.py` (405行)
4. `meeting_management/application/use_cases.py` (402行)

**拆分策略**:

```python
# Before: 单个God Class
class GroupMessagingApplication:
    async def create_channel(...): ...          # 40行
    async def post_message(...): ...            # 60行
    async def upload_attachment(...): ...       # 50行
    async def agent_reply_stream(...): ...      # 80行
    async def archive_conversation(...): ...    # 45行
    # ... 10+ methods, 500+ lines

# After: 按聚合根 + CQRS拆分
# 文件: channel_commands.py
class ChannelCommands:
    async def create(cmd: CreateChannelCommand) -> ChannelResult: ...
    async def archive(cmd: ArchiveRequest) -> None: ...

# 文件: message_commands.py
class MessageCommands:
    async def post(cmd: PostMessageCommand) -> MessageResult: ...
    async def upload_attachment(cmd: UploadAttachmentCommand) -> AttachmentResult: ...

# 文件: agent_reply_service.py
class AgentReplyService:
    async def reply_stream(req: AgentReplyRequest) -> AsyncIterator[AgentReplyStreamEvent]: ...

# 文件: conversation_queries.py
class ConversationQueries:
    async def get_messages(channel_id, limit) -> list[MessageResult]: ...
    async def download_attachment(file_id) -> AttachmentDownloadResult: ...

# 文件: application.py (facade)
class GroupMessagingApplication:
    def __init__(self, ...):
        self.channels = ChannelCommands(...)
        self.messages = MessageCommands(...)
        self.agent_replies = AgentReplyService(...)
        self.queries = ConversationQueries(...)
```

**预期收益**:
- 每个文件降到100-150行
- 职责清晰，易于测试
- 减少import混乱

---

#### 3.4 提取通用Use Case模板（1-2天）

**问题**: 大量重复的UoW + Repository + 权限校验模板

```python
# 当前每个use case重复的模式
async def some_command(self, cmd: SomeCommand) -> SomeResult:
    # 权限校验
    if not await self._policy.can_access(cmd.user_id, cmd.resource_id):
        raise PermissionDenied("无权限")

    # UoW模板
    async with self._uow_factory() as uow:
        entity = await uow.repo.get(cmd.id)
        if not entity:
            raise ResourceNotFound()

        entity.do_something(cmd.param)
        await uow.commit()

    # 审计
    await self._audit_port.log(...)

    return to_result(entity)
```

**优化方案**: 定义Command Handler基类

```python
# shared_kernel/command_handler.py
class CommandHandler(Generic[TCommand, TResult]):
    async def execute(self, cmd: TCommand) -> TResult:
        await self._authorize(cmd)
        result = await self._handle_transactional(cmd)
        await self._post_commit(cmd, result)
        return result

    @abstractmethod
    async def _handle_transactional(self, cmd: TCommand) -> TResult:
        """子类实现核心逻辑，自动包裹UoW"""
        pass

    async def _authorize(self, cmd: TCommand) -> None:
        """默认空实现，需要时覆盖"""
        pass

    async def _post_commit(self, cmd: TCommand, result: TResult) -> None:
        """提交后动作：审计、事件发布等"""
        pass

# 使用示例
class CreateProposalHandler(CommandHandler[CreateProposalCommand, ProposalResult]):
    async def _handle_transactional(self, cmd):
        async with self._uow_factory() as uow:
            proposal = Proposal(...)
            await uow.proposals.add(proposal)
            await uow.commit()
            return to_result(proposal)

    async def _authorize(self, cmd):
        if not await self._policy.can_create(cmd.user_id):
            raise PermissionDenied()
```

**预期收益**:
- 每个use case节省8-10行模板代码，121处UoW模板 ≈ 1,000行
- 统一异常处理和审计

---

#### 3.5 合并重复的Result转换函数（1天）

**问题**: 每个Context都有大量`_xxx_result()`函数

```python
# 当前每个Context重复定义
def _proposal_result(proposal: Proposal) -> ProposalResult:
    return ProposalResult(
        id=proposal.id,
        code=proposal.code,
        title=proposal.title,
        # ... 15 fields
    )

def _review_result(review: ProposalReview) -> ProposalReviewResult:
    return ProposalReviewResult(
        id=review.id,
        # ... 10 fields
    )
```

**优化方案**:
1. Domain模型实现`to_contract()`方法
2. 或使用dataclass转换库（如cattrs）
3. 删除所有手写转换函数

```python
# 方案1: Domain方法
@dataclass
class Proposal:
    id: UUID
    code: str
    title: str
    # ...

    def to_result(self) -> ProposalResult:
        return ProposalResult(**asdict(self))

# 方案2: 泛型转换器
def to_contract(domain_obj: TDomain, contract_cls: type[TContract]) -> TContract:
    return converter.structure(asdict(domain_obj), contract_cls)
```

**预期收益**（已按实测修正）: use_cases 层实际只有 **12 个**手工转换函数（初版报告估 200+ 系高估）。
infrastructure 层另有 19 个 row→domain 映射，但各 aggregate 字段不重叠，**不建议合并**。
本项收益有限（~200行），优先级降低；真正的结构性冗余是 meeting_management 的
row→domain→result 双重搬运（见 2.4(d)），那是分层策略问题。

---

### P2 - 可维护性提升（1-2周）

#### 3.6 重构LLM网关（2-3天）

**当前问题**:
- `factory.py` 288行，包含工厂+注册+可用性检查
- `fallback.py` 276行，failover逻辑与LangChain紧耦合

**拆分方案**:
```
app/llm/
├── core/
│   ├── provider.py         # Provider抽象
│   ├── registry.py         # 注册表
│   └── health.py           # 健康检查（已有）
├── adapters/
│   ├── openai_adapter.py   # 各provider适配器
│   ├── anthropic_adapter.py
│   └── ...
├── resilience/
│   ├── failover.py         # Failover策略
│   ├── circuit_breaker.py  # 熔断器
│   └── retry.py            # 重试策略
└── gateway.py              # 统一入口facade
```

**收益**:
- 每个文件<150行
- 支持新provider只需加adapter
- 测试友好

---

#### 3.7 重构飞书集成（2天）

**当前**: `feishu/client.py` 364行单体类

**拆分方案**:
```
app/integrations/feishu/
├── auth.py           # OAuth + Token刷新
├── contacts.py       # 通讯录/组织架构
├── messaging.py      # 消息发送
├── events.py         # 事件订阅
└── client.py         # 组合facade (< 100行)
```

---

#### 3.8 标准化Port接口（3-5天）

**问题**: 69个adapters但未标准化

**方案**: 定义通用Port协议族

```python
# shared_kernel/ports.py
class Repository(Protocol[T]):
    async def get(self, id: UUID) -> T | None: ...
    async def add(self, entity: T) -> None: ...
    async def list(self, **filters) -> list[T]: ...

class ExternalResourcePort(Protocol):
    """外部资源访问标准接口"""
    async def fetch(self, resource_id: str) -> bytes: ...
    async def store(self, content: bytes) -> str: ...

class NotificationPort(Protocol):
    async def send(self, recipient: str, message: str) -> None: ...
```

**收益**:
- 减少定制化adapter
- 统一测试mock方式
- 新Context复用已有adapter

---

### P3 - 性能与质量（持续进行）

#### 3.9 添加代码质量门禁（1天）

```yaml
# .github/workflows/quality.yml
- name: Code Metrics Check
  run: |
    # 单文件不超过300行
    python scripts/check_file_size.py --max-lines 300

    # 单函数不超过50行
    radon cc app -a -nb --min C

    # 圈复杂度不超过10
    xenon --max-absolute B --max-modules A --max-average A app

    # 重复代码率<5%
    pylint app --disable=all --enable=duplicate-code
```

#### 3.10 重复代码消除（等后台任务结果）

等待`tokensave_redundancy`任务完成后，针对性重构高相似度函数对。

---

## 四、量化目标（按实测数据修正）

### 4.1 代码量目标

各项收益的原始分析口径（保留用于追踪后续清理潜力）：

| 优化项 | 预估减少行数 | 依据 |
|-------|------------|------|
| 删除 `app/models/` 兼容层（P0 完成后） | ~5,000行 | 220KB ORM 兼容入口 |
| 删除 `app/schemas/`、`app/agents/`、`app/llm/`、`app/integrations/` 兼容入口 | ~3,000行 | 引用归零后可删 |
| CommandHandler 消除 UoW 模板 | ~1,000行 | 121处 × 8行 |
| 机械去重（附件链路 + 技术性 Port/实现） | ~350行 | 2.4(e) 实测 300~390 |
| Result 转换收敛 | ~200行 | 12个函数 |
| **合计** | **~9,500行 (-21%)** | 45,341 → ~35,800 |

拆分超大类**不减少总行数**（只是重新分布），但它是可维护性的最大收益项。

| 指标 | 当前 | 目标 |
|-----|------|------|
| 总行数 | 45,341行 | ~35,800行 (-21%) |
| 最大文件 | 501行 | <250行 |
| 300+行文件 | 11个 | 0个 |
| contexts 对兼容层引用 | 145处 (models 74 + core 25 + agents 18 + llm 16 + integrations 11 + schemas 1) | 0处 |

### 4.2 质量指标目标

| 指标 | 当前（实测） | 目标 |
|-----|------|------|
| ruff | 全绿 | 保持全绿 |
| mypy | 641文件零错误 | 保持零错误 |
| pytest 基线 | 729项收集；717 passed、1 skipped、11 deselected | 保持全绿 |
| Clock/SystemClock 副本 | 11 / 10份 | 1份（需 docs/20 决策） |
| UoW Protocol 样板 | 15处×12行 | 1个基Protocol |

---

## 五、执行计划

### 第1周: 架构清理（P0）
- [ ] Day 1-2: 清除contexts对app.models依赖
- [ ] Day 3: 标准化UnitOfWork模式
- [ ] Day 4-5: 验证架构门禁 + 回归测试

### 第2周: 代码压缩（P1.1）
- [ ] Day 1-2: 拆分`GroupMessagingApplication`
- [ ] Day 3-4: 拆分`AssistantConversationsApplication`
- [ ] Day 5: 拆分其余2个超大类

### 第3周: 模板化（P1.2）
- [ ] Day 1-2: 实现CommandHandler基类
- [ ] Day 3-4: 重构10个典型use case
- [ ] Day 5: 消除Result转换函数

### 第4周: 基础设施优化（P2）
- [ ] Day 1-2: 重构LLM网关
- [ ] Day 3: 重构飞书集成
- [ ] Day 4-5: 标准化Port接口

---

## 六、风险与缓解

| 风险 | 影响 | 缓解措施 |
|-----|------|---------|
| 重构破坏现有功能 | 高 | 每步都跑全量测试，小步提交 |
| 开发进度延误 | 中 | 先做P0/P1，P2可渐进式 |
| 团队不熟悉新模式 | 中 | 提供重构示例 + Code Review |
| 迁移期新旧代码共存 | 低 | 架构门禁阻止回退 |

---

## 七、详细代码度量

### 7.1 模板代码统计（已验证）

| 模板类型 | 出现次数 | 说明 |
|---------|---------|-----------|
| UoW模板 (`async with uow_factory`) | 121次 | 每处8-10行样板，CommandHandler可消除约1,000行 |
| UoW Protocol 四件套声明 | 15处 | 每处约12行逐字样板 |
| 异步方法定义 | 617个 | - |
| Port/Repository接口 | 169个 | 大部分是刻意的Context自治设计，勿盲目合并 |
| Result转换函数（use_cases层） | 12个 | 手工逐字段复制 |
| row→domain映射（infrastructure层） | 19个 | 字段不重叠，仅统一命名风格 |
| 应用错误抛出 | 122次 | 已统一走shared_kernel，无需处理 |
| Dataclass定义 | 347个 | 合理使用 |

**机械去重上限**: ~350行；**模板消除上限**: ~1,000行；大头在兼容层退出（~8,000行）。

### 7.2 架构分层统计

| 层 | 目录数 | 文件数 | 代码行 | 占比 |
|---|--------|--------|--------|------|
| Application | 33 | ~150 | 5,371行 (use_cases.py) | 11.8% |
| Infrastructure | 33 | ~200 | ~15,000行 (估算) | 33.0% |
| Domain | 21 | 41 | ~3,500行 (估算) | 7.7% |
| Entrypoints | - | ~80 | ~6,000行 (估算) | 13.2% |
| 迁移期代码 | - | ~170 | ~11,000行 (估算) | 24.3% |
| Platform | - | ~50 | 4,500行 | 9.9% |

**contexts目录占总代码量**: 76.0% (34,587/45,490行)

### 7.3 重复模式识别

#### 典型重复模式1: UoW + 查询 + 权限校验

```python
# 出现121次的模式
async def some_method(self, id: UUID, user_id: UUID) -> Result:
    async with self._uow_factory() as uow:              # 重复
        entity = await uow.repo.get(id)                 # 重复
        if not entity:                                  # 重复
            raise ResourceNotFound("xx不存在")           # 重复
        # 实际业务逻辑仅2-3行
        await uow.commit()                              # 重复
    return to_result(entity)                            # 重复
```

**优化建议**: 装饰器 + 泛型Repository

#### 典型重复模式2: 实体创建模板

```python
# 出现60+次的模式
entity = Entity(
    id=self._identifiers.new_id(),        # 重复
    creator_id=cmd.user_id,               # 重复
    create_time=self._clock.now(),        # 重复
    # 业务字段
)
```

**优化建议**: Entity基类提供`create_new()`工厂方法

#### 典型重复模式3: Result转换

```python
# 23个文件中重复的模式
def _xxx_result(entity: Entity) -> Result:
    return Result(
        id=entity.id,
        name=entity.name,
        # ... 逐字段复制
    )
```

**优化建议**: 使用cattrs/pydantic自动转换

---

## 八、具体重构示例

### 示例1: 拆分GroupMessagingApplication

**Before** (501行单文件):
```python
# app/contexts/business/group_messaging/application/use_cases.py
class GroupMessagingApplication:
    def __init__(self, 8个依赖): ...

    async def create_channel(self, ...): ...          # 30行
    async def add_members(self, ...): ...             # 25行
    async def remove_member(self, ...): ...           # 20行
    async def disband_channel(self, ...): ...         # 15行
    async def mark_read(self, ...): ...               # 12行
    async def channels_with_unread(self, ...): ...    # 10行
    async def list_messages(self, ...): ...           # 15行
    async def post_message_stream(self, ...): ...     # 80行
    async def subscribe_user_messages(self, ...): ... # 20行
    async def archive_channel(self, ...): ...         # 25行
    async def upload_attachment(self, ...): ...       # 30行
    async def download_attachment(self, ...): ...     # 25行
    async def promote_message(self, ...): ...         # 35行
    async def agent_reply_stream(self, ...): ...      # 100行
    # ... 私有辅助方法 15个，共80行
```

**After** (5个文件，每个<150行):

```python
# app/contexts/business/group_messaging/application/channel_lifecycle.py
class ChannelLifecycle:
    """频道生命周期管理"""
    def __init__(self, uow_factory, clock, identifiers): ...

    async def create(self, cmd: CreateChannelCommand) -> ChannelResult: ...
    async def archive(self, id: UUID) -> ChannelResult: ...
    async def disband(self, id: UUID, owner_id: UUID) -> None: ...

# app/contexts/business/group_messaging/application/membership.py
class MembershipManagement:
    """成员管理"""
    async def add_members(self, channel_id, members): ...
    async def remove_member(self, channel_id, member_id): ...

# app/contexts/business/group_messaging/application/messaging.py
class MessagingOperations:
    """消息收发"""
    async def post_human_message(self, cmd) -> MessageResult: ...
    async def list_messages(self, channel_id, limit) -> list[MessageResult]: ...
    async def mark_read(self, channel_id, user_id) -> None: ...

# app/contexts/business/group_messaging/application/ai_interaction.py
class AIInteractionService:
    """AI交互编排"""
    async def stream_agent_reply(self, request) -> AsyncIterator[Event]: ...
    async def trigger_auto_reply(self, channel_id, agents) -> None: ...

# app/contexts/business/group_messaging/application/attachments.py
class AttachmentService:
    """附件管理"""
    async def upload(self, cmd: UploadCommand) -> AttachmentResult: ...
    async def download(self, path, user_id) -> bytes: ...
```

**收益**:
- 每个类职责单一，易于测试
- 501行 → 5个文件各100-120行
- 构造函数依赖从8个降至2-3个
- 新增功能时改动范围小

---

### 示例2: CommandHandler基类消除模板代码

**Before** (重复121次):
```python
class ProposalApplication:
    async def create(self, cmd: CreateProposalCommand) -> ProposalResult:
        # 8行模板代码
        async with self._uow_factory() as uow:
            if not await self._policy.can_create(cmd.user_id):
                raise PermissionDenied()
            proposal = Proposal(...)
            await uow.proposals.add(proposal)
            await uow.commit()
            await self._audit.log("创建会商", user_id=cmd.user_id)
        return to_result(proposal)  # 2行转换代码
```

**After** (模板代码0行):
```python
# shared_kernel/handlers.py
class CommandHandler(Generic[TCmd, TResult]):
    """通用Command处理器，自动处理UoW/权限/审计"""

    async def execute(self, cmd: TCmd) -> TResult:
        await self._authorize(cmd)
        async with self._uow_factory() as uow:
            result = await self._handle(cmd, uow)
            await uow.commit()
        await self._post_commit(cmd, result)
        return result

    @abstractmethod
    async def _handle(self, cmd: TCmd, uow: UnitOfWork) -> TResult:
        """子类只写核心逻辑"""
        pass

# 使用
class CreateProposalHandler(CommandHandler[CreateProposalCommand, ProposalResult]):
    async def _handle(self, cmd, uow):
        proposal = Proposal.create(
            title=cmd.title,
            creator_id=cmd.user_id,
            identifiers=self._identifiers,
            clock=self._clock,
        )
        await uow.proposals.add(proposal)
        return proposal.to_result()

    async def _authorize(self, cmd):
        if not await self._policy.can_create(cmd.user_id):
            raise PermissionDenied()
```

**收益**:
- 每个handler节省8-10行模板代码
- 121个use case × 8行 = 968行代码消除
- 统一异常处理和日志记录
- 易于添加横切关注点（如性能监控）

---

## 九、质量基线（2026-07-28 实测）

- `uv run ruff check .` → **All checks passed**
- `uv run mypy app` → **Success: no issues found in 641 source files**

即当前问题不是"坏代码"，而是**结构性冗余**：门禁工具测不出的重复 Port、模板代码、
超大 Application 类。重构期间每一步都必须保持这两项 + pytest 全绿。

---

## 十、参考资料

- [DDD领域边界规范](./20-DDD领域边界与分层架构规范.md)
- [开发规范手册](./05-开发规范手册.md)
- [架构评审报告](./16-架构评审与改进路线图.md)
