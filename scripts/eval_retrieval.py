"""知识检索黄金评测集打分器（D3 / docs/21 §D）：固定 golden 集比较检索质量，防迁移/调参退化。

指标（docs/21 知识迁移门禁 L1566）：Recall@K、NDCG@K、零结果率、延迟。判「相关」按
**document_name**（跨多次入库稳定，file_id 每次入库重生成不可作 golden 键）。

纯指标函数（recall_at_k/ndcg_at_k/aggregate）无 DB、可被单测导入；runner 打真库跑 fused 生产路径。

用法：uv run python scripts/eval_retrieval.py [golden.json] [--min-recall 0.8] [--min-ndcg 0.7]
  golden.json 省略时用 scripts/retrieval_golden.example.json
  （占位样例，真实标注集由业务 SME 按真语料补）。
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoldenItem:
    """一条评测：query + top_k + 该查询下人工判定相关的 document_name 集合。"""

    query: str
    top_k: int
    relevant_names: frozenset[str]


def load_golden(path: Path) -> list[GoldenItem]:
    """载入 golden JSON（list of {query, top_k, relevant_names[]}），基本校验。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("golden 集根须为 list")
    items: list[GoldenItem] = []
    for i, row in enumerate(raw):
        query = row.get("query", "").strip()
        names = row.get("relevant_names") or []
        top_k = int(row.get("top_k", 5))
        if not query or not isinstance(names, list) or top_k <= 0:
            raise ValueError(f"golden[{i}] 非法：query/relevant_names/top_k 缺失或越界")
        items.append(GoldenItem(query, top_k, frozenset(map(str, names))))
    return items


def recall_at_k(retrieved: Sequence[str], relevant: frozenset[str], k: int) -> float:
    """命中的相关项 / 全部相关项，前 k。relevant 为空视作无可召回 → 1.0（不拖累均值）。"""
    if not relevant:
        return 1.0
    hit = sum(1 for name in dict.fromkeys(retrieved[:k]) if name in relevant)
    return hit / len(relevant)


def ndcg_at_k(retrieved: Sequence[str], relevant: frozenset[str], k: int) -> float:
    """二元相关 NDCG@K：DCG=Σ rel_i/log2(i+2)，IDCG=理想排序。无相关项 → 1.0。"""
    if not relevant:
        return 1.0
    dcg = sum(
        1.0 / math.log2(i + 2) for i, name in enumerate(retrieved[:k]) if name in relevant
    )
    ideal = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal))
    return dcg / idcg if idcg else 0.0


@dataclass(frozen=True)
class Aggregate:
    """整个 golden 集的聚合指标。"""

    n: int
    mean_recall: float
    mean_ndcg: float
    zero_result_rate: float


def aggregate(
    retrieved_per_query: Sequence[Sequence[str]],
    golden: Sequence[GoldenItem],
) -> Aggregate:
    """按查询取均值；零结果率=检索返回空的查询占比。两序列须等长同序。"""
    if len(retrieved_per_query) != len(golden):
        raise ValueError("retrieved 与 golden 数量不一致")
    n = len(golden)
    if n == 0:
        return Aggregate(0, 0.0, 0.0, 0.0)
    recalls = [
        recall_at_k(r, g.relevant_names, g.top_k)
        for r, g in zip(retrieved_per_query, golden, strict=True)
    ]
    ndcgs = [
        ndcg_at_k(r, g.relevant_names, g.top_k)
        for r, g in zip(retrieved_per_query, golden, strict=True)
    ]
    zeros = sum(1 for r in retrieved_per_query if len(r) == 0)
    return Aggregate(n, sum(recalls) / n, sum(ndcgs) / n, zeros / n)


# ponytail: 留后（打分器已可复用）——真实标注集、引用一致性(/ask citations)、
# 旧/新检索对比(Phase 2 远端索引)。


async def _run(golden_path: Path, min_recall: float, min_ndcg: float) -> int:
    import sys
    import time

    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # Windows 控制台

    from app.contexts.foundations.governance.system_configuration.public import (
        list_configurations,
    )
    from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
        SearchKnowledgeQuery,
    )
    from app.contexts.foundations.knowledge.knowledge_retrieval.public import search_knowledge
    from app.core import runtime_config
    from app.platform.database import async_session_factory

    golden = load_golden(golden_path)
    print(f"golden 集 {golden_path.name}：{len(golden)} 条查询\n")

    retrieved_per_query: list[list[str]] = []
    async with async_session_factory() as db:
        configurations = await list_configurations(db)
        runtime_config.load({item.key: item.value for item in configurations})
        for item in golden:
            t0 = time.perf_counter()
            result = await search_knowledge(
                db, SearchKnowledgeQuery(query=item.query, top_k=item.top_k)
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            names = [hit.document_name for hit in result.hits]
            retrieved_per_query.append(names)
            r = recall_at_k(names, item.relevant_names, item.top_k)
            nd = ndcg_at_k(names, item.relevant_names, item.top_k)
            print(
                f"《{item.query[:28]}》 recall={r:.2f} ndcg={nd:.2f} "
                f"{elapsed_ms:.0f}ms hits={len(names)}"
            )

    agg = aggregate(retrieved_per_query, golden)
    print(
        f"\n聚合 n={agg.n} mean_recall={agg.mean_recall:.3f} "
        f"mean_ndcg={agg.mean_ndcg:.3f} zero_result_rate={agg.zero_result_rate:.3f}"
    )
    if agg.mean_recall < min_recall or agg.mean_ndcg < min_ndcg:
        print(f"✗ 低于门槛 recall≥{min_recall} ndcg≥{min_ndcg} —— 检索质量退化")
        return 1
    print("✓ 达标")
    return 0


if __name__ == "__main__":
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(description="知识检索黄金评测集打分")
    parser.add_argument(
        "golden",
        nargs="?",
        default=str(Path(__file__).with_name("retrieval_golden.example.json")),
    )
    parser.add_argument("--min-recall", type=float, default=0.0)
    parser.add_argument("--min-ndcg", type=float, default=0.0)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(Path(args.golden), args.min_recall, args.min_ndcg)))
