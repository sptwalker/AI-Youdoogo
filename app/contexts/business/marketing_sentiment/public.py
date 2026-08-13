"""营销舆情 Context 门面：跨 Context 只经此导入检测函数与契约（bootstrap 消费）。"""

from __future__ import annotations

from app.contexts.business.marketing_sentiment.anomaly import detect_sentiment_anomalies
from app.contexts.business.marketing_sentiment.contracts import (
    SentimentAlert,
    SentimentSignal,
    SentimentThresholds,
)

__all__ = [
    "SentimentAlert",
    "SentimentSignal",
    "SentimentThresholds",
    "detect_sentiment_anomalies",
]
