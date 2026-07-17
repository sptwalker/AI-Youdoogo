"""混合检索真库诊断（docs/15 阶段A.1 验证）：并排打印 向量臂 / 关键词臂 / RRF融合 三路结果。

目的：隔离出**关键词臂的独立贡献**——证明它召回了向量臂漏掉的精确匹配（专名/型号/编码）。
做法：入库一小撮受控语料（近义型号 盒子A3/A5 等），对若干探针查询各跑三路检索、并排对比，跑完清理。

用法：uv run python scripts/probe_hybrid.py
前置：① 真 Postgres 在跑且已 `alembic upgrade head`（pg_trgm 扩展+索引生效）；
② 配好 embedding 密钥。
说明：会产生极少量真实 embedding 调用费用；入库的临时文档在结束时软删清理。
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 允许以脚本方式直跑
sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows GBK 控制台兼容

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session_factory  # noqa: E402
from app.knowledge import ingest, retrieval  # noqa: E402
from app.models.system import SysUser  # noqa: E402
from app.services import config_service  # noqa: E402
from app.services.knowledge_base_service import get_default_kb  # noqa: E402

# 受控语料：故意造"型号近义、语义相近"的干扰项——向量易混，trgm 能精确区分。
_CORPUS: list[tuple[str, str]] = [
    ("盒子A3规格", "创想悦动盒子A3是入门款智能盒子，支持1080P，售价399元，2024年上市。"),
    ("盒子A5规格", "创想悦动盒子A5是旗舰款智能盒子，支持4K HDR，售价899元，2025年上市。"),
    ("盒子A7规格", "创想悦动盒子A7是专业款智能盒子，支持8K，售价1599元，2026年上市。"),
    ("退货政策", "所有智能盒子产品支持7天无理由退货，需保持包装完好，运费由买家承担。"),
    ("固件升级", "智能盒子可通过设置-系统-固件升级在线更新到最新版本，升级中勿断电。"),
]

# 探针查询：精确型号 + 一个纯语义问题（对照组，两臂都该命中）
_PROBES: list[str] = ["盒子A5 的售价和分辨率", "A7 支持几K", "盒子怎么退货"]

_TOPN = 5


def _fmt(hits: list[retrieval.Hit]) -> str:
    if not hits:
        return "    （空）"
    return "\n".join(
        f"    {i + 1}. {h.file_name}  (dist={h.distance:.3f})  {h.chunk_text[:24]}…"
        for i, h in enumerate(hits)
    )


async def _run() -> int:
    async with async_session_factory() as db:
        # 独立脚本覆盖层为空，先载入 sys_config（embedding 端点/密钥可能存这里）
        from app.core import runtime_config

        runtime_config.load(await config_service.all_values(db))

        hybrid = await config_service.resolve(db, "retrieval_hybrid_enabled", True)
        print(f"混合检索开关 retrieval_hybrid_enabled = {hybrid}\n")

        kb_id = (await get_default_kb(db)).id
        uploader = (
            await db.execute(select(SysUser.id).where(SysUser.is_delete.is_(False)).limit(1))
        ).scalar_one_or_none()
        if uploader is None:
            print("库中无任何用户，无法作为上传人入库。先创建 admin（scripts/create_admin.py）。")
            return 1
        file_ids: list[uuid.UUID] = []
        try:
            print("① 入库受控语料 …")
            for title, text in _CORPUS:
                kf = await ingest.ingest_text(
                    db, title=f"[probe] {title}", text=text,
                    uploader_id=uploader, knowledge_base_id=kb_id, category="probe",
                )
                file_ids.append(kf.id)
            print(f"   已入库 {len(file_ids)} 篇。\n")

            kb_scope = [kb_id]
            for q in _PROBES:
                print(f"② 查询：《{q}》")
                vec = await retrieval._vector_arm(db, q, _TOPN, kb_scope)
                kw = await retrieval._keyword_arm(db, q, _TOPN, kb_scope)
                fused = await retrieval.search(db, q, top_k=_TOPN, visible_kb_ids=kb_scope)
                print("  【向量臂】\n" + _fmt(vec))
                print("  【关键词臂 pg_trgm】\n" + _fmt(kw))
                print("  【RRF 融合(最终)】\n" + _fmt(fused))
                # 关键指标：融合首位是否精确命中查询里的型号
                top = fused[0].chunk_text if fused else ""
                print(f"  → 融合首位命中：{top[:32]}…\n")
            print("提示：看关键词臂是否把'精确型号那篇'顶到前排，而向量臂把近义型号混在一起。")
            return 0
        finally:
            print("\n③ 清理探针文档 …")
            for fid in file_ids:
                try:
                    await ingest.delete_file(db, fid)
                except Exception as exc:  # noqa: BLE001 - 清理尽力而为
                    print(f"   清理 {fid} 失败：{exc}")
            print("   完成。")


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
