# F2 知识集合化 — 交接文档

> 历史交接快照：本文描述 F2 开发中期状态。知识库 API、测试、权限范围和后续混合检索现已实现；当前事实以源码、迁移 head 与 docs/15 为准。

**日期：** 2026-07-13  
**分支：** `dev`  
**最后提交：** `0bcf452` fix(F1): 修复编辑智能体时提示词被清空  
**当前状态：** F2 后端核心层已完成，**未提交**，API 层 + 测试 + 质量门 待完成

---

## 已完成（未提交，working tree 有改动）

| 文件 | 状态 | 说明 |
|------|------|------|
| `app/models/knowledge.py` | ✅ 已改 | 新增 `KnowledgeBase`、`DataSource` 模型；`KnowledgeFile` 加 `knowledge_base_id` FK |
| `app/models/__init__.py` | ✅ 已改 | 导出 `KnowledgeBase`、`DataSource` |
| `alembic/versions/012_knowledge_base.py` | ✅ 新建 | 建表 + 种子"公司公共知识库" + 存量文件回填 |
| `app/knowledge/scope.py` | ✅ 新建 | `resolve_visible_kb_ids()` — 可见范围推导（契约②减法隔离） |
| `app/services/knowledge_base_service.py` | ✅ 新建 | KB CRUD：`create_kb / update_kb / delete_kb / list_kbs / get_default_kb` |
| `app/services/data_source_service.py` | ✅ 新建 | DS CRUD：`create_ds / update_ds / delete_ds / list_ds`（密钥脱敏） |
| `app/knowledge/ingest.py` | ✅ 已改 | 三入口（`ingest_file/ingest_text/ingest_feishu_doc`）均加 `knowledge_base_id` 必填参数 |
| `app/knowledge/retrieval.py` | ✅ 已改 | `search()` + `answer()` 加 `visible_kb_ids` 可选参数（传 None=不过滤，传空列表=无结果） |

**迁移已应用到 dev DB：** `alembic_version = 012_knowledge_base`  
**DB 验证：** 公司公共库种子 ✓，3 条存量文件全部回填 ✓，`data_source` 表存在 ✓

---

## 待完成（下一个对话接着做）

### 1. 更新 `app/api/v1/knowledge.py`（P0，会导致现有接口 500）

三个 ingest 端点需要传 `knowledge_base_id`：
- 默认取 `get_default_kb(db).id`（公司公共库），可选接受请求体中的 `knowledge_base_id` 字段
- `ask` 端点需要先调 `resolve_visible_kb_ids(db, department_id=user.department_id, is_admin=user.role=="admin")` 再传给 `retrieval.answer(..., visible_kb_ids=ids)`

```python
# 伪代码示意
kb_id = body.knowledge_base_id or (await get_default_kb(db)).id
kf = await ingest.ingest_file(..., knowledge_base_id=kb_id)

# ask 端点
ids = await resolve_visible_kb_ids(db, department_id=user.department_id, is_admin=user.role=="admin")
result = await retrieval.answer(db, body.query, body.top_k, user_id=user.id, visible_kb_ids=ids)
```

### 2. 新建 `app/api/v1/knowledge_bases.py`

KB CRUD 路由（admin 管理，普通用户只读）：
```
GET    /knowledge-bases          → list_kbs
POST   /knowledge-bases          → create_kb (admin)
PATCH  /knowledge-bases/{id}     → update_kb (admin)
DELETE /knowledge-bases/{id}     → delete_kb (admin)
```

### 3. 新建 `app/api/v1/data_sources.py`

DS CRUD 路由（admin）：
```
GET    /data-sources             → list_ds
POST   /data-sources             → create_ds (admin)
PATCH  /data-sources/{id}        → update_ds (admin)
DELETE /data-sources/{id}        → delete_ds (admin)
```

### 4. 在 `app/main.py` 挂载两个新路由

### 5. 写测试 `tests/test_knowledge_base.py`

最小覆盖：
- 创建 KB（company/department/personal scope）
- 删除含文件的 KB 被拒
- 公司公共库不可删
- `resolve_visible_kb_ids` 隔离逻辑（admin 全见，普通用户不见他人 personal 库）

### 6. 质量门

```bash
uv run ruff check app/ tests/
uv run mypy app/
uv run pytest -x -q
```

### 7. 提交

```bash
git add -A
git commit -m "feat(F2): 知识集合化 — KnowledgeBase/DataSource + scope 隔离 + ingest/retrieval 接线"
git push
```

---

## 关键设计决策（不要改）

- **scope 三档：** `company`（全员）/ `department`（部门树）/ `personal`（owner + admin）
- **减法隔离：** 默认全公司可见，`is_confidential=True` 才收窄到部门树
- **密钥安全：** `DataSource.secret_ref` 存 `.env` 变量名，绝不存明文；`list_ds` 只回显 `secret_status`（not_set/configured/missing）
- **CEO = admin 用户：** 无 CEO agent，`is_admin=True` 在 `resolve_visible_kb_ids` 中全库可见
- **存量文件：** 全部回填到"公司公共知识库"（`is_default=True`），不破坏现有功能

---

## 环境信息

- **本地 DB：** `postgresql+asyncpg://postgres:postgres@localhost:5433/youdoo`（Docker 容器 youdoo-postgres，宿主机 5433）
- **本地后端：** `uv run uvicorn app.main:app --reload`（localhost:8000）
- **本地前端：** `cd frontend && npm run dev`（localhost:5173）
- **登录：** admin / Youdoo@2026
- **uv 路径：** `C:/Users/walker/.local/bin/uv.exe`
- **迁移命令：** `uv run alembic upgrade head`

---

## 当前 todo 状态

```
[completed] 阶段1~5 主链
[completed] F1 组织架构
[in_progress] F2 知识集合化（本文档描述的工作）
[pending] F3 真人工作台
[pending] F4 权限精细化（resource_grant 显式授权）
[pending] F5 跨部门协作治理
```
