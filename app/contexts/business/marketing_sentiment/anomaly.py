"""纯舆情异常检测：负面占比突增 / 竞品重大动作 / 政策变动三类命中。

纯函数、无 DB、无 IO——阈值由调用侧传入（走 runtime_config，不在此硬编码）。
镜像 ``operational_analytics.domain.anomaly.detect_metric_anomalies`` 的 loop-and-append 形制。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.contexts.business.marketing_sentiment.contracts import (
    SentimentAlert,
    SentimentSignal,
    SentimentThresholds,
)


def detect_sentiment_anomalies(
    signals: Sequence[SentimentSignal],
    thresholds: SentimentThresholds,
) -> tuple[SentimentAlert, ...]:
    """按 kind 逐条判定，命中即追加告警。无命中返回空元组（下游据此决定不发事件）。"""
    # 占比是外部数据解析来的浮点，恰在阈值上会栽 IEEE754 表示误差（0.30-0.10=0.19999…<0.2）；
    # 留一个远小于任何业务阈值的容差，让「恰达阈值」稳定命中，不因二进制抖动漏报。
    eps = 1e-9
    alerts: list[SentimentAlert] = []
    for signal in signals:
        if signal.kind == "negative_ratio":
            jump = signal.negative_ratio - signal.baseline_ratio
            # 突增幅度达阈值 且 当前占比过地板（双条件：滤掉基线本就高、或小样本抖动）
            if (
                jump >= thresholds.negative_ratio_jump - eps
                and signal.negative_ratio >= thresholds.negative_ratio_floor - eps
            ):
                alerts.append(
                    SentimentAlert(
                        channel=signal.channel,
                        kind="negative_spike",
                        severity="high",
                        message=(
                            f"{signal.channel} 负面占比 {signal.negative_ratio:.0%}"
                            f"（较基线突增 {jump:+.0%}）：{signal.summary}"
                        ),
                    )
                )
        elif signal.kind == "competitor_move":
            # 只认「重大」竞品动作——日常动作（is_major=False）不触发，避免噪声
            if thresholds.competitor_major and signal.is_major:
                alerts.append(
                    SentimentAlert(
                        channel=signal.channel,
                        kind="competitor_move",
                        severity="high",
                        message=f"竞品重大动作：{signal.summary}",
                    )
                )
        elif signal.kind == "policy_change":
            # 政策变动出现即显著（不看 is_major），仅由开关整体门控
            if thresholds.policy_change:
                alerts.append(
                    SentimentAlert(
                        channel=signal.channel,
                        kind="policy_change",
                        severity="high",
                        message=f"政策变动：{signal.summary}",
                    )
                )
        # 其它 kind 静默忽略（未知信号类型不臆造告警）
    return tuple(alerts)
