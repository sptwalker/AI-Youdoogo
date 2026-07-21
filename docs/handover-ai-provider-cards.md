# 交接文档 — AI 配置卡片化（多 Provider 动态管理）

> 历史交接快照：本文描述 2026-07-14 尚未开发时的计划。AI Provider 卡片、主备切换、加密存储与管理 UI 现已实现；不要把下方“待做任务”作为当前进度。

**日期：** 2026-07-14
**分支：** `dev`（最后提交 `9352def`：密钥 UI 化 + AI/外部数据/飞书配置栏 + 运营看板拉取按钮）
**当前状态：** 系统主体（阶段0~6 + docs/13 管理框架 F1~F5 + 多轮迭代）**全部已交付并推送**。当前正**规划中**「AI 配置卡片化」功能——**设计已批准、代码尚未开始写**。
**接手第一件事：** 按 `~/.claude/plans/warm-enchanting-wreath.md`（已批准的完整方案）实现 AI 配置卡片化。

---

## ⚠️ 本会话的工具错误（新会话请避免）
1. **AskUserQuestion**：每个 question 对象必须有顶层 `question` 字段（本会话多次漏写导致报错）。
2. **todowrite**：`status` 字段多次被注入 `\r` 导致校验失败（"in_progress" 变成 "in\r_progress"）。写 todo 时 status 用纯 ASCII `pending`/`in_progress`/`completed`，content 也尽量纯文本。
3. **会话末尾回环**：最后几轮出现工具结果反复触发同一写入。新会话从干净状态开始即可。

---

## 一、待做任务：AI 配置卡片化（已批准方案）
**完整方案在 `~/.claude/plans/warm-enchanting-wreath.md`**（这是最终版，逐文件列了改动）。核心：
- 把 AI 密钥从「固定预置项」改成 **BH 风格动态卡片**：新增卡片填 名称/档位/地址/Key/模型 → 测连通自动保存 → 多张卡片 → 设「主要使用/禁用」→ 一键检测全部（绿灯正常/红灯异常/灰禁用）。
- **已确认的两个决策**：①**卡片分「日常/推理」档**（对接现有 model_role，会商/提案预研走推理档）；②**必须建卡片**，无卡片时 AI 不可用，**不回退 .env**（`_PROVIDER_KEY_FIELD` 预置废弃）。
- **参考源在本地**：`c:\Users\walker\Documents\walker\Vibecode\Bottleneck-Hunter`——`bottleneck_hunter/auth/store.py`(custom_providers 表)、`web/custom_provider_api.py`(CRUD/test/primary/toggle)、`web/model_tester.py`(连通测试)、`llm_clients/factory.py`(`set_provider_status(inactive,primary)`)。
- **我们的 factory 同源移植**（`app/llm/factory.py` 已有 `register_custom_provider`/`_CUSTOM_PROVIDERS`），只缺 primary/inactive 概念 + DB 卡片持久化。

**实现顺序（方案里 10 步）**：
1. `app/models/ai_provider.py`（name/tier/base_url/api_key/api_key_hint/model/is_primary/is_active/last_test_*）+ `__init__` 导出
2. `app/llm/factory.py` 加 `_INACTIVE_PROVIDERS`/`_PRIMARY_PROVIDER_BY_TIER`/`set_provider_status`；`provider_available` 加 inactive 判断；废弃 `_PROVIDER_KEY_FIELD`
3. `app/llm/model_tester.py`（`test_card(base_url,api_key,model)` → ChatOpenAI ainvoke "hi" 限时，返回 status/latency/msg）
4. `app/services/ai_provider_service.py`（create/update/delete/list脱敏/set_primary同档互斥/toggle_active/test_provider/**sync_to_factory**）
5. `app/api/v1/ai_providers.py`（仅 admin：list/create/patch/delete/test/primary/toggle/**test-all**）+ 挂 main + 每次变更后 sync_to_factory + 审计
6. `alembic/versions/019_ai_provider.py`（建表 + **删迁移018种的 llm 密钥项** deepseek/dashscope/zhipu/anthropic_api_key；embedding/飞书/TD 密钥保留）
7. `app/llm/roles.py::get_llm_for_role` 改为按 tier 取该档 primary 卡片 + 同档 active 作 failover；无卡片抛 `NoAvailableProviderError`；`app/agents/base.py` 的 `_LLM_ROLE_BY_TIER` 相应调整
8. `tests/test_ai_provider.py`（脱敏/set_primary互斥/toggle/sync_to_factory/get_llm_for_role无卡片抛错/test_card打桩）
9. 前端 `api/aiProviders.ts` + `pages/AiProviders.tsx`（新增卡片ModalForm→自动test→保存；卡片网格+状态灯+设主用/启停/编辑/删；顶部「检测全部」）+ 菜单「系统管理」加「AI 配置」+ SystemConfig 移除 AI 大模型密钥栏改引导链接
10. 质量门（ruff+mypy+pytest，**LLM 网关测试要适配**：从 .env key 改为建卡片）+ 前端 build + 迁移019上live + 真机验收 + commit

**注意接线点**：`get_llm_for_role`/`_LLM_ROLE_BY_TIER` 是每次 AI 调用的核心路径，改动面广；`test_llm_gateway.py` 本会话已把 patch 目标从 `factory.get_settings` 改为 `runtime_config.get_settings`，卡片化后还要再适配（改为注入卡片而非 settings key）。

---

## 二、系统整体现状（已完成，勿重做）
- **阶段0~6主链** + **docs/13 管理框架 F1~F5** 全部交付。迁移链 **001~018**（live DB 已到 018）。
- **F1** 组织树+AI员工；**F2** 知识集合化+范围隔离；**F3** 真人工作台；**F3'** 协作空间(@Agent五件套护栏)；**F4a/b/c** 审计配置/显式授权resource_grant/协作治理；**F5a** 真人工作桌面(取代workbench)；**F5b/c** 管理台(系统日志/配置/数据接口/知识库集合/授权/连通性测试)。
- **F5 后多轮迭代**（均已推）：
  - **AI 员工检索知识库**（scope.resolve_agent_visible_kb_ids + run_agent use_knowledge，任务执行开启，真机验证 AI 开卷引用来源）
  - **知识库归属**（上传选目标库 + 文件移库）
  - **侧边栏两组分组**（业务/系统管理，`layout="side"` + 分组节点补 path + defaultOpenAll）
  - **工作桌面加 AI 顾问对话窗**（POST /agents/roles/{id}/consult）+ 布局调整（去快捷入口、我的任务右移）
  - **AI 输出统一 Markdown 渲染**（react-markdown + components/Markdown.tsx；提示词/配置值保留纯文本）
  - **ThinkingData 接入脚手架**（配置驱动：td_base_url/sql/映射 sys_config可编辑；ingest_from_thinkingdata + POST /ops-data/sync-thinkingdata + 运营看板拉取按钮；本地假TD打桩测试。**真机连TD待用户提供 HOST/密钥/表结构**）
  - **密钥可 UI 填写（改了红线）**：CLAUDE.md 铁律#4 + docs/13 §3/决策⑩ 已改。新增 `app/core/runtime_config.py` 覆盖层（sys_config 覆盖 .env）；main lifespan 启动载入；config_service.set_config 改后同步；LLM factory/飞书/embedding/TD/notify 全改经 runtime_config.effective；密钥 list 脱敏(is_secret列)+审计打码。系统配置页按分类分栏。

## 三、关键红线与架构（不可动摇）
- AI 仅建议/分析/辅助执行权，一切生效动作必须真人确认+留痕。`run_agent` 不 bind_tools（AI 无法调用任何函数）；生效动作只被 API 层真人调用。
- 知识可见性：真人减法隔离(默认可见+机密收窄)；**AI 员工更严**(resolve_agent_visible_kb_ids：公司公共库+本部门库，不含他部门)。
- 密钥：**禁止硬编码**；可存 .env 或 sys_config(is_secret，UI填，读时脱敏)，经 runtime_config 覆盖。

## 四、F1-F5 审计遗留的可选加固项（非阻断，按需做）
审计事务性(audit与生效动作分两次commit)、并发行锁FOR UPDATE(convert_to_task等)、task验收角色门、热点索引。

## 五、环境备忘
- **DB**：`postgresql+asyncpg://postgres:postgres@localhost:5433/youdoo`（Docker `youdoo-postgres`，宿主 5433），Docker 栈(pg/redis/minio) healthy，迁移到 018。
- **uv**：`C:/Users/walker/.local/bin/uv.exe`；`uv run alembic upgrade head` / `uv run pytest -q` / `uv run ruff check app/ tests/` / `uv run mypy app`。
- **后端**：`uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`（**未用 --reload，改后端代码需手动重启**；8000 常被旧进程占，先 netstat+taskkill）。
- **前端**：`cd frontend && npm run dev`（**5174**，5173 常被更早会话的旧 vite 占；两者都读同源码）。
- **登录**：admin / Youdoo@2026。
- **连通性**：DeepSeek(LLM) + 通义(embedding) + 飞书 可用；**ThinkingData 未配置**（待用户 HOST/密钥）。
- **测试基线**：167 全绿；ruff/mypy 干净。
- **Windows 坑**：控制台 GBK，Python 打印 emoji/中文会崩，脚本设 `PYTHONIOENCODING=utf-8`；git 会警告 LF→CRLF（无害，.gitattributes 已管 sh/Dockerfile）。

## 六、记忆
长期记忆在 `~/.claude/.../memory/youdoo-project-status.md`（已随开发持续更新，含全部阶段决策与现状）。
