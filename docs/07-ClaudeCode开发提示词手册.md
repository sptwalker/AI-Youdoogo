# 07-ClaudeCode开发提示词手册

> 本手册技术栈段落以项目根 `CLAUDE.md` 为唯一事实源：技术栈如有调整，先改 `CLAUDE.md`，再同步本手册与相关文档。
>
> 修订记录：2026-07-11 依据技术栈修订决策更新（Python 3.12 + uv、LangGraph 1.x 阶段3引入、DeepSeek 主力多模型降级链、timescaledb-ha:pg16 单镜像、前端阶段2初始化）。

## 1. 全局初始化上下文提示词（首次开发必用）

每次启动 Claude Code 开发，优先加载本全局上下文，锁定项目规范与架构：

```Plain Text
你现在是YOUDOO AI企业管理决策大脑系统的专属开发工程师，全程基于项目标准化文档开发，严格遵守所有架构、规范、技术栈约束，禁止自由发挥架构与功能。

【项目信息】
项目名称：创想悦动AI智能公司管理和决策辅助系统
项目定位：多AI智能体企业办公协同+管理决策辅助系统
适用企业：创想悦动科技公司

【强制技术栈约束】（以项目根 CLAUDE.md 为唯一事实源）
语言/工具链：Python 3.12 + uv（uv sync / uv run）
后端：FastAPI + Uvicorn
ORM：SQLAlchemy 2.0 async + asyncpg + Alembic
校验/配置：Pydantic v2 + pydantic-settings（app/core/config.py 唯一配置入口）
数据库：PostgreSQL 16（timescale/timescaledb-ha:pg16 单镜像，内置 TimescaleDB + pgvector）
缓存/文件：Redis / MinIO
大模型：DeepSeek 主力（deepseek-chat 日常 / deepseek-reasoner 会商推理），降级链 → Qwen → GLM；统一网关在 app/llm/（langchain-core + langchain-openai）
智能体编排：LangGraph 1.x（阶段3才引入，之前禁止安装）
飞书：自研异步 httpx 客户端 app/integrations/feishu/（不用 lark-oapi SDK）
前端：React + Ant Design Pro（阶段2才初始化）
代码规范：Ruff + Mypy 全量校验，严格PEP8
测试：Pytest 核心模块覆盖率≥80%

【项目目录规范】
严格遵循项目固定目录结构（见 docs/05），不随意新增目录；新增一级目录须先修订 docs/05

【开发铁律】
1. 文档优先，无设计文档不开发业务代码
2. 单次只开发一个独立模块，先确认思路再编码
3. 所有代码必须带类型注解、文档字符串、核心注释
4. 敏感配置环境变量存储，禁止硬编码
5. 所有接口必须有权限、参数校验
6. AI仅做辅助，核心逻辑人工兜底审核
7. 开发完成必须通过Lint、类型检查、单元测试（uv run ruff check . / uv run mypy app / uv run pytest 全绿）
```

## 2. 项目初始化搭建分步提示词

### 2.1 初始化项目骨架

```Plain Text
请按照项目标准目录结构，初始化完整项目脚手架，完成：
1. 生成 uv 管理的 pyproject.toml，配置所有核心依赖（uv sync 可直接安装）
2. 生成完整.gitignore文件
3. 搭建app/core配置体系，基于pydantic-settings管理环境变量
4. 初始化FastAPI主入口，配置健康检查接口
5. 编写docker-compose.yml，部署postgres（timescale/timescaledb-ha:pg16）、redis、minio基础服务
```

### 2.2 数据库与ORM搭建

```Plain Text
请完成数据库基础搭建：
1. 编写通用base模型，封装基础公共字段
2. 完成用户、部门、角色、权限核心ORM模型
3. 配置Alembic数据库迁移工具
4. 实现数据库会话连接管理
5. 生成对应Pydantic请求响应模型
```

### 2.3 权限鉴权体系开发

```Plain Text
请开发完整的JWT权限鉴权体系：
1. 实现密码加密、JWT令牌生成与校验
2. 开发登录、登出、刷新令牌接口
3. 实现接口级别权限依赖校验
4. 完成用户、角色、权限CRUD接口
5. 编写对应单元测试验证权限拦截逻辑
```

### 2.4 大模型网关与知识库开发

```Plain Text
请开发模型网关与基础知识库能力：
1. 封装统一大模型调用网关，支持 DeepSeek 主力调用与 Qwen/GLM 降级链、用量记录（首版记日志）、异常捕获
2. 实现文档上传、解析、分块、向量化、pgvector存储
3. 开发语义检索接口，支持内容溯源
4. 完成知识库基础管理接口
5. 编写测试用例验证检索准确性
```

## 3. 通用模块开发模板

```Plain Text
请基于docs目录对应设计文档，开发指定模块功能。
【开发范围】
1. 功能点1
2. 功能点2
【输入输出规范】
【依赖模块】
【验收标准】
1. 通过ruff、mypy全量检查
2. 包含完整类型注解与文档注释
3. 单元测试覆盖率≥80%
4. 接口权限、参数校验齐全
请先输出实现思路，确认后再编写代码。
```
