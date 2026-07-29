"""检索评测打分器纯数学测试（无 DB）：recall/ndcg/聚合 + golden 载入校验。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from scripts.eval_retrieval import (
    GoldenItem,
    aggregate,
    load_golden,
    ndcg_at_k,
    recall_at_k,
)


def test_recall_at_k() -> None:
    rel = frozenset({"a", "b"})
    assert recall_at_k(["a", "b", "c"], rel, 5) == 1.0
    assert recall_at_k(["a", "x", "y"], rel, 5) == 0.5
    assert recall_at_k(["a", "b"], rel, 1) == 0.5  # 截断到 k=1 只见 a
    assert recall_at_k(["a", "a"], rel, 5) == 0.5  # 去重后不双计
    assert recall_at_k([], rel, 5) == 0.0
    assert recall_at_k([], frozenset(), 5) == 1.0  # 无相关项=无可漏


def test_ndcg_at_k() -> None:
    rel = frozenset({"a", "b"})
    assert ndcg_at_k(["a", "b"], rel, 5) == pytest.approx(1.0)  # 完美排序
    assert ndcg_at_k(["x", "y"], rel, 5) == 0.0  # 全不相关
    # 相关项排第 2、3 位：DCG=1/log2(3)+1/log2(4)，IDCG=1/log2(2)+1/log2(3)
    dcg = 1 / math.log2(3) + 1 / math.log2(4)
    idcg = 1 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k(["x", "a", "b"], rel, 5) == pytest.approx(dcg / idcg)
    assert ndcg_at_k([], frozenset(), 5) == 1.0


def test_aggregate_and_zero_result_rate() -> None:
    golden = [
        GoldenItem("q1", 5, frozenset({"a"})),
        GoldenItem("q2", 5, frozenset({"b"})),
    ]
    agg = aggregate([["a"], []], golden)
    assert agg.n == 2
    assert agg.mean_recall == 0.5  # q1 命中, q2 空
    assert agg.zero_result_rate == 0.5
    with pytest.raises(ValueError):
        aggregate([["a"]], golden)  # 数量不一致


def test_load_golden_example_parses() -> None:
    example = Path(__file__).resolve().parent.parent / "scripts" / "retrieval_golden.example.json"
    items = load_golden(example)
    assert len(items) >= 1
    assert all(item.query and item.relevant_names and item.top_k > 0 for item in items)


def test_load_golden_rejects_bad(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('[{"query": "", "relevant_names": []}]', encoding="utf-8")
    with pytest.raises(ValueError):
        load_golden(bad)
