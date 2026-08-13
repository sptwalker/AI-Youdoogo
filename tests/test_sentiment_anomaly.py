"""舆情异常检测纯单测（离线、无 DB）：三类命中 + 阈值边界。

镜像 tests/test_anomaly.py 风格；阈值均显式传入（证明本域不硬编码）。
"""

from app.contexts.business.marketing_sentiment.public import (
    SentimentSignal,
    SentimentThresholds,
    detect_sentiment_anomalies,
)

_TH = SentimentThresholds(
    negative_ratio_jump=0.2,
    negative_ratio_floor=0.3,
    competitor_major=True,
    policy_change=True,
)


def test_no_signals_no_alerts() -> None:
    assert detect_sentiment_anomalies((), _TH) == ()


# ── 负面占比突增 ─────────────────────────────────────────
def test_negative_spike_hits_when_jump_and_floor_met() -> None:
    sig = SentimentSignal(
        channel="电商评论", kind="negative_ratio", summary="差评集中",
        negative_ratio=0.55, baseline_ratio=0.30,  # jump=0.25≥0.2 且 0.55≥0.3
    )
    alerts = detect_sentiment_anomalies([sig], _TH)
    assert len(alerts) == 1
    assert alerts[0].kind == "negative_spike"
    assert "电商评论" in alerts[0].message


def test_negative_spike_skipped_when_jump_below_threshold() -> None:
    # 突增仅 0.15 < 0.2 → 不命中（哪怕当前占比过地板）
    sig = SentimentSignal(
        channel="社媒", kind="negative_ratio", summary="小幅上升",
        negative_ratio=0.45, baseline_ratio=0.30,
    )
    assert detect_sentiment_anomalies([sig], _TH) == ()


def test_negative_spike_skipped_below_floor() -> None:
    # 突增够（0.25）但当前占比 0.25 < 地板 0.3 → 滤小样本噪声，不命中
    sig = SentimentSignal(
        channel="资讯", kind="negative_ratio", summary="基数低",
        negative_ratio=0.25, baseline_ratio=0.0,
    )
    assert detect_sentiment_anomalies([sig], _TH) == ()


def test_negative_spike_boundary_exactly_at_thresholds_hits() -> None:
    # 恰好等于两阈值（jump=0.2、ratio=0.3）→ 命中（>= 边界含等号）
    sig = SentimentSignal(
        channel="电商评论", kind="negative_ratio", summary="临界",
        negative_ratio=0.30, baseline_ratio=0.10,
    )
    assert len(detect_sentiment_anomalies([sig], _TH)) == 1


# ── 竞品重大动作 ─────────────────────────────────────────
def test_competitor_major_hits() -> None:
    sig = SentimentSignal(
        channel="竞品渠道", kind="competitor_move", summary="竞品发布新品", is_major=True
    )
    alerts = detect_sentiment_anomalies([sig], _TH)
    assert len(alerts) == 1 and alerts[0].kind == "competitor_move"


def test_competitor_minor_move_skipped() -> None:
    sig = SentimentSignal(
        channel="竞品渠道", kind="competitor_move", summary="竞品日常推文", is_major=False
    )
    assert detect_sentiment_anomalies([sig], _TH) == ()


def test_competitor_gated_off_by_threshold() -> None:
    th = SentimentThresholds(competitor_major=False)
    sig = SentimentSignal(
        channel="竞品渠道", kind="competitor_move", summary="重大但开关关", is_major=True
    )
    assert detect_sentiment_anomalies([sig], th) == ()


# ── 政策变动 ─────────────────────────────────────────────
def test_policy_change_hits_regardless_of_major() -> None:
    sig = SentimentSignal(
        channel="行业资讯", kind="policy_change", summary="新版合规要求", is_major=False
    )
    alerts = detect_sentiment_anomalies([sig], _TH)
    assert len(alerts) == 1 and alerts[0].kind == "policy_change"


def test_policy_change_gated_off_by_threshold() -> None:
    th = SentimentThresholds(policy_change=False)
    sig = SentimentSignal(channel="行业资讯", kind="policy_change", summary="被关闭")
    assert detect_sentiment_anomalies([sig], th) == ()


# ── 混合 + 未知类型 ──────────────────────────────────────
def test_mixed_signals_and_unknown_kind() -> None:
    signals = [
        SentimentSignal("电商评论", "negative_ratio", "差评", negative_ratio=0.6, baseline_ratio=0.30),  # noqa: E501
        SentimentSignal("竞品渠道", "competitor_move", "重大", is_major=True),
        SentimentSignal("行业资讯", "policy_change", "新政"),
        SentimentSignal("社媒", "unknown_kind", "忽略"),  # 未知类型不臆造
    ]
    alerts = detect_sentiment_anomalies(signals, _TH)
    assert {a.kind for a in alerts} == {"negative_spike", "competitor_move", "policy_change"}
    assert all(a.to_dict()["severity"] == "high" for a in alerts)
