"""知识写侧迁移对账（⑥a / docs/22 §3）：切 ``knowledge_index_mode=remote`` 前的放行门。

复用 ``reconcile.content_hash`` 的确定性指纹原语，只加**知识文档的对账口径**与**纯比对器**：
证「远端知识服务索引结果 == 本地索引结果」——业务内容一致，非字节一致（向量随模型版本漂移，
不入 hash；docs/22 §2「不比字节，比业务内容」）。

对账口径（入 hash 的业务字段）：``file_name / knowledge_base_id / category / uploader_id /
status`` + **有序 chunk 文本**（分块算法两端逐字一致，分块漂移即失配）。排除技术簿记
（``id`` 作 join 键单独比、``create_time / file_size / storage_path / mime_type / source_ref``
两端天然不同或派生，入 hash 必假阳性；docs/22 §2.2）。

比对器纯函数、无 DB、无副作用（失配只列 ``document_id`` + 两侧 hash 供人工核因，**绝不改数据**，
docs/22 §5「不做自动数据修复」）。运维双库读取在 ``_run``（DB import 惰性，纯函数免 DB 可测）。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from scripts.reconcile import content_hash


def document_fingerprint(
    *,
    file_name: str,
    knowledge_base_id: object,
    category: str | None,
    uploader_id: object,
    status: str,
    chunk_texts: Sequence[str],
) -> str:
    """一篇知识文档的业务内容指纹。chunk_texts 须按 chunk_index 升序（顺序入 hash）。"""
    return content_hash(
        {
            "file_name": file_name,
            "knowledge_base_id": knowledge_base_id,
            "category": category,
            "uploader_id": uploader_id,
            "status": status,
            "chunks": list(chunk_texts),  # list 值：canonical_json 保序，chunk 顺序敏感
        }
    )


@dataclass(frozen=True, slots=True)
class Mismatch:
    """一条内容失配：两侧都有该文档，但业务指纹不同。带 id + 两侧 hash 供人工核因。"""

    document_id: str
    source_hash: str
    target_hash: str


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    matched: tuple[str, ...]  # 两侧指纹一致的 document_id
    mismatched: tuple[Mismatch, ...]  # 两侧都有但内容失配
    missing_in_target: tuple[str, ...]  # 源有目标无（远端漏索引）
    missing_in_source: tuple[str, ...]  # 目标有源无（远端多索引 / 脏数据）

    @property
    def ok(self) -> bool:
        """三关全绿（行数守恒 + 内容 parity）才具备切流条件。"""
        return not (self.mismatched or self.missing_in_target or self.missing_in_source)

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "matched_count": len(self.matched),
            "mismatched": [
                {"document_id": m.document_id, "source_hash": m.source_hash,
                 "target_hash": m.target_hash}
                for m in self.mismatched
            ],
            "missing_in_target": list(self.missing_in_target),
            "missing_in_source": list(self.missing_in_source),
        }


def reconcile(source: Mapping[str, str], target: Mapping[str, str]) -> ReconcileReport:
    """逐 document_id 比对源↔目标指纹（docs/22 §3：计数守恒 + 内容 parity 合一）。"""
    src_ids, tgt_ids = set(source), set(target)
    both = src_ids & tgt_ids
    matched = tuple(sorted(i for i in both if source[i] == target[i]))
    mismatched = tuple(
        Mismatch(i, source[i], target[i]) for i in sorted(both) if source[i] != target[i]
    )
    return ReconcileReport(
        matched=matched,
        mismatched=mismatched,
        missing_in_target=tuple(sorted(src_ids - tgt_ids)),
        missing_in_source=tuple(sorted(tgt_ids - src_ids)),
    )


# ponytail: 抽样 N 条对账（默认 --limit 500）；全量分批留运维按 document_id 游标续跑。
# 向量本体不入指纹（embedding 随模型/版本漂移）——本门只保内容保真，向量质量归 ⑤ 读侧 golden。


async def _hashes_from_dsn(dsn: str, *, limit: int) -> dict[str, str]:
    """从一个库读活跃文档 → {document_id: 业务指纹}。源/目标同一 ORM（迁移期同库、拆分期同形）。"""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.models.knowledge import KnowledgeFile, KnowledgeVector

    engine = create_async_engine(dsn)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            files = list(
                (
                    await db.execute(
                        select(KnowledgeFile)
                        .where(KnowledgeFile.is_delete.is_(False))
                        .order_by(KnowledgeFile.create_time.desc())
                        .limit(limit)
                    )
                ).scalars()
            )
            file_ids = [f.id for f in files]
            chunks: dict[object, list[tuple[int, str]]] = {fid: [] for fid in file_ids}
            if file_ids:
                for fid, idx, text in (
                    await db.execute(
                        select(
                            KnowledgeVector.file_id,
                            KnowledgeVector.chunk_index,
                            KnowledgeVector.chunk_text,
                        ).where(KnowledgeVector.file_id.in_(file_ids))
                    )
                ).all():
                    chunks[fid].append((idx, text))
            return {
                str(f.id): document_fingerprint(
                    file_name=f.file_name,
                    knowledge_base_id=f.knowledge_base_id,
                    category=f.category,
                    uploader_id=f.uploader_id,
                    status=f.status,
                    chunk_texts=[t for _, t in sorted(chunks[f.id])],
                )
                for f in files
            }
    finally:
        await engine.dispose()


async def _run(*, source_dsn: str, target_dsn: str, limit: int) -> ReconcileReport:
    source = await _hashes_from_dsn(source_dsn, limit=limit)
    target = await _hashes_from_dsn(target_dsn, limit=limit)
    return reconcile(source, target)


def _print_ids(label: str, ids: Iterable[str]) -> None:
    items = list(ids)
    if items:
        print(f"  {label}: {len(items)} 条 -> {items[:10]}{' …' if len(items) > 10 else ''}")


if __name__ == "__main__":
    import argparse
    import asyncio
    import json
    import os
    import sys

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows 控制台

    parser = argparse.ArgumentParser(description="知识写侧迁移对账（切 remote 前的放行门）")
    parser.add_argument(
        "--source-dsn", default=os.getenv("DATABASE_URL", ""),
        help="本地索引权威源（默认 DATABASE_URL）",
    )
    parser.add_argument(
        "--target-dsn", default=os.getenv("KV_RECONCILE_TARGET_DSN", ""),
        help="远端知识服务索引结果库（一次性临时库；置 KV_RECONCILE_TARGET_DSN）",
    )
    parser.add_argument("--limit", type=int, default=500, help="抽样条数（默认 500）")
    args = parser.parse_args()

    if not args.source_dsn or not args.target_dsn:
        print("需 --source-dsn 与 --target-dsn（或 DATABASE_URL / KV_RECONCILE_TARGET_DSN）。")
        print("远端目标库须先由知识服务用同批 IndexTextCommand 索引后再对账。")
        sys.exit(2)

    report = asyncio.run(
        _run(source_dsn=args.source_dsn, target_dsn=args.target_dsn, limit=args.limit)
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    print(f"\n对账{'通过 ✓ 具备切流条件' if report.ok else '未过 ✗ 停在本地'}")
    _print_ids("失配", (m.document_id for m in report.mismatched))
    _print_ids("远端漏索引", report.missing_in_target)
    _print_ids("远端多索引", report.missing_in_source)
    sys.exit(0 if report.ok else 1)
