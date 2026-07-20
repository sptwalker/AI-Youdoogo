"""飞书开放平台异步客户端（自研 httpx，不用 lark-oapi）。

移植自 feishu_project_manager 并做减法：
- 凭证只从 app.core.config.get_settings() 读取（feishu_app_id / feishu_app_secret），
  无 DB 系统设置分支，密钥只走环境变量。
- OAuth 登录相关方法未移植，阶段1接入飞书登录时按需补。
"""

import asyncio
import json
import time
from typing import Any

import httpx


class FeishuAPIError(Exception):
    """飞书 API 错误。"""


class FeishuAuthError(FeishuAPIError):
    """飞书认证错误。"""


class FeishuClient:
    """飞书 API 客户端（tenant_access_token 维度）。"""

    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        # tenant_access_token 缓存（按凭证 key 失效：凭证变更后下次取 token 自动重取）
        self._tenant_token: str | None = None
        self._tenant_token_expire_at: float = 0.0
        self._tenant_cred_key: str | None = None

    @staticmethod
    def _creds() -> tuple[str, str]:
        """读取当前飞书应用凭证：sys_config 覆盖(可 UI 填) → .env(Settings)。"""
        from app.core import runtime_config

        return (
            str(runtime_config.effective("feishu_app_id", "") or ""),
            str(runtime_config.effective("feishu_app_secret", "") or ""),
        )

    def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端。"""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """关闭 HTTP 客户端。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_tenant_access_token(self) -> str:
        """获取并缓存 tenant_access_token（发送消息、操作文档/多维表格使用）。

        缓存按当前凭证(app_id+secret) key：凭证变更后，下次取 token 自动重取；
        并提前 60 秒过期，避免边界失效。
        """
        app_id, app_secret = self._creds()
        cred_key = f"{app_id}|{app_secret}"
        now = time.monotonic()
        if (
            self._tenant_token
            and self._tenant_cred_key == cred_key
            and now < self._tenant_token_expire_at
        ):
            return self._tenant_token

        client = self._get_client()
        try:
            response = await client.post(
                f"{self.BASE_URL}/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FeishuAuthError(f"HTTP error getting tenant access token: {e}") from e
        except httpx.RequestError as e:
            raise FeishuAPIError(f"Request error getting tenant access token: {e}") from e

        data = response.json()
        if data.get("code") != 0:
            raise FeishuAuthError(f"Failed to get tenant access token: {data.get('msg')}")

        token: str = data["tenant_access_token"]
        self._tenant_token = token
        self._tenant_token_expire_at = now + max(0, int(data.get("expire", 7200)) - 60)
        self._tenant_cred_key = cred_key
        return token

    async def _post_authed(
        self,
        path: str,
        json_body: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """以 tenant_access_token 发送 POST 请求并解析飞书响应。"""
        token = await self.get_tenant_access_token()
        client = self._get_client()
        try:
            response = await client.post(
                f"{self.BASE_URL}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                params=params,
                json=json_body,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FeishuAPIError(f"HTTP error on POST {path}: {e}") from e
        except httpx.RequestError as e:
            raise FeishuAPIError(f"Request error on POST {path}: {e}") from e

        data = response.json()
        if data.get("code") != 0:
            raise FeishuAPIError(f"Feishu API error on POST {path}: {data.get('msg')}")
        result: dict[str, Any] = data.get("data", {})
        return result

    async def _get_authed(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """以 tenant_access_token 发送 GET 请求并解析飞书响应。"""
        token = await self.get_tenant_access_token()
        client = self._get_client()
        try:
            response = await client.get(
                f"{self.BASE_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FeishuAPIError(f"HTTP error on GET {path}: {e}") from e
        except httpx.RequestError as e:
            raise FeishuAPIError(f"Request error on GET {path}: {e}") from e

        data = response.json()
        if data.get("code") != 0:
            raise FeishuAPIError(f"Feishu API error on GET {path}: {data.get('msg')}")
        result: dict[str, Any] = data.get("data", {})
        return result

    # ---------------- 消息 ----------------

    async def send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: dict[str, Any],
        receive_id_type: str = "user_id",
    ) -> dict[str, Any]:
        """发送消息（im/v1/messages），content 会被序列化为 JSON 字符串。"""
        return await self._post_authed(
            "/im/v1/messages",
            params={"receive_id_type": receive_id_type},
            json_body={
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False),
            },
        )

    async def send_text(
        self, receive_id: str, text: str, receive_id_type: str = "user_id"
    ) -> dict[str, Any]:
        """发送纯文本消息。"""
        return await self.send_message(receive_id, "text", {"text": text}, receive_id_type)

    async def send_card(
        self, receive_id: str, card: dict[str, Any], receive_id_type: str = "user_id"
    ) -> dict[str, Any]:
        """发送交互式卡片消息。"""
        return await self.send_message(receive_id, "interactive", card, receive_id_type)

    # ---------------- 云文档 docx ----------------

    async def create_document(self, title: str) -> str:
        """创建飞书云文档（docx），返回 document_id。需要 docx:document 权限。"""
        data = await self._post_authed(
            "/docx/v1/documents",
            json_body={"title": title[:800]},
        )
        doc = data.get("document", {})
        document_id = doc.get("document_id")
        if not document_id:
            raise FeishuAPIError("create_document 未返回 document_id")
        return str(document_id)

    @staticmethod
    def _run(content: str, bold: bool = False, color: int | None = None) -> dict[str, Any]:
        """构造一个 text_run 文本片段，可加粗/上色。color 为飞书字体色枚举(1-7)。"""
        run: dict[str, Any] = {"text_run": {"content": content}}
        style: dict[str, Any] = {}
        if bold:
            style["bold"] = True
        if color:
            style["text_color"] = color
        if style:
            run["text_run"]["text_element_style"] = style
        return run

    @staticmethod
    def text_block(content: str) -> dict[str, Any]:
        """构造一个文本段落块（block_type=2）。"""
        return {
            "block_type": 2,
            "text": {"elements": [FeishuClient._run(content)]},
        }

    @staticmethod
    def rich_block(runs: list[tuple[Any, ...]]) -> dict[str, Any]:
        """构造含多片段的文本段落块。runs: [(content, bold?, color?), ...]。"""
        els = []
        for r in runs:
            content = r[0]
            bold = r[1] if len(r) > 1 else False
            color = r[2] if len(r) > 2 else None
            els.append(FeishuClient._run(content, bold, color))
        return {"block_type": 2, "text": {"elements": els}}

    @staticmethod
    def heading_block(content: str, level: int = 1) -> dict[str, Any]:
        """构造标题块。level 1/2/3 → heading1/2/3（block_type 3/4/5）。"""
        bt = {1: 3, 2: 4, 3: 5}.get(level, 3)
        key = f"heading{level}"
        return {"block_type": bt, key: {"elements": [FeishuClient._run(content)]}}

    async def append_document_blocks(
        self, document_id: str, blocks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """向文档根节点追加块（block_id 用 document_id 表示根）。需要 docx:document 权限。

        飞书「创建块」接口单次最多 50 个子块、且每秒≤3 次，故按 50/批 分批顺序追加；
        不传 index 默认追加到末尾，多批顺序调用即保证整体内容顺序与 blocks 一致。
        """
        batch = 50  # 飞书单次创建子块数量上限
        last: dict[str, Any] = {}
        for i in range(0, len(blocks), batch):
            chunk = blocks[i : i + batch]
            last = await self._post_authed(
                f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                json_body={"children": chunk},
            )
            # 限速：每秒≤3 次，非最后一批时批次间留间隔
            if i + batch < len(blocks):
                await asyncio.sleep(0.4)
        return last

    async def get_document_raw_content(self, document_id: str) -> str:
        """获取云文档纯文本内容（知识库分块向量化的输入）。

        需要 docx:document:readonly 权限。
        ponytail: 结构化块读取（blocks 列表）暂不封装——知识库只需纯文本，需要结构时再加。
        """
        data = await self._get_authed(f"/docx/v1/documents/{document_id}/raw_content")
        return str(data.get("content", ""))

    # ---------------- 多维表格 bitable ----------------

    async def bitable_list_records(
        self,
        app_token: str,
        table_id: str,
        page_size: int = 100,
        filter_expr: str | None = None,
        max_records: int | None = None,
    ) -> list[dict[str, Any]]:
        """列出多维表格记录（自动翻页取全量；max_records 可设上限防超大表）。

        飞书单页最多 100 条，靠 has_more/page_token 翻页。
        """
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": page_size}
            if filter_expr:
                params["filter"] = filter_expr
            if page_token:
                params["page_token"] = page_token
            data = await self._get_authed(
                f"/bitable/v1/apps/{app_token}/tables/{table_id}/records", params
            )
            items.extend(data.get("items") or [])
            if max_records is not None and len(items) >= max_records:
                return items[:max_records]
            page_token = data.get("page_token")
            if not data.get("has_more") or not page_token:
                return items

    async def bitable_create_record(
        self, app_token: str, table_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """创建多维表格记录。"""
        return await self._post_authed(
            f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
            json_body={"fields": fields},
        )

    async def bitable_update_record(
        self, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """更新多维表格记录。"""
        token = await self.get_tenant_access_token()
        client = self._get_client()
        url = f"{self.BASE_URL}/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
        try:
            response = await client.put(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={"fields": fields},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise FeishuAPIError(f"HTTP error updating bitable record: {e}") from e
        except httpx.RequestError as e:
            raise FeishuAPIError(f"Request error updating bitable record: {e}") from e

        data = response.json()
        if data.get("code") != 0:
            raise FeishuAPIError(f"Failed to update bitable record: {data.get('msg')}")
        result: dict[str, Any] = data.get("data", {})
        return result

    # ── 通讯录（contact/v3）：组织同步用（I1，docs/18）────────────────
    async def list_departments(
        self, parent_department_id: str = "0", page_size: int = 50
    ) -> list[dict[str, Any]]:
        """递归拉取部门树全量（从 parent 起，自动翻页 + 递归子部门）。

        飞书 contact/v3/departments/{id}/children 返回直接子部门；根用 '0'（企业根）。
        需权限 contact:department.base:readonly。返回每部门含 open_department_id/name/parent。
        """
        out: list[dict[str, Any]] = []

        async def _children(dept_id: str) -> None:
            page_token: str | None = None
            while True:
                params: dict[str, Any] = {
                    "page_size": page_size, "department_id_type": "open_department_id",
                }
                if page_token:
                    params["page_token"] = page_token
                data = await self._get_authed(
                    f"/contact/v3/departments/{dept_id}/children", params
                )
                items = data.get("items") or []
                out.extend(items)
                for it in items:  # 递归子部门
                    child_id = it.get("open_department_id")
                    if child_id:
                        await _children(child_id)
                page_token = data.get("page_token")
                if not data.get("has_more") or not page_token:
                    break

        await _children(parent_department_id)
        return out

    async def list_users_by_department(
        self, department_id: str, page_size: int = 50
    ) -> list[dict[str, Any]]:
        """拉取某部门下员工全量（自动翻页）。需权限 contact:user.base:readonly。

        返回每员工含 open_id/name/en_name/mobile/department_ids/avatar/job_title 等。
        """
        out: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            params: dict[str, Any] = {
                "department_id": department_id, "page_size": page_size,
                "department_id_type": "open_department_id",
            }
            if page_token:
                params["page_token"] = page_token
            data = await self._get_authed("/contact/v3/users/find_by_department", params)
            out.extend(data.get("items") or [])
            page_token = data.get("page_token")
            if not data.get("has_more") or not page_token:
                return out


# 全局飞书客户端实例
feishu_client = FeishuClient()
