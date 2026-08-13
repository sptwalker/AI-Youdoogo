"""营销舆情检测契约：信号输入、告警输出、可配阈值（全 frozen、无 DB）。

镜像 ``operational_analytics.agent_contracts`` 的 MetricRowInput/MetricAlert 形制
（frozen slots dataclass + 告警带 to_dict），但舆情三类命中异质，故信号带 ``kind`` 判别。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SentimentSignal:
    """一条归一后的舆情信号（由上游取数执行器解析外部 API 后喂入，本域只做纯判定）。

    ``kind`` 判别三类命中所需字段：
      - ``negative_ratio``：负面占比突增——用 ``negative_ratio``（当前）与 ``baseline_ratio``。
      - ``competitor_move``：竞品重大动作——用 ``is_major`` 区分「重大」与日常动作。
      - ``policy_change``：行业政策变动——出现即视为显著（``is_major`` 忽略）。
    """

    channel: str  # 来源渠道：电商评论 / 社交媒体 / 行业资讯 / 竞品渠道
    kind: str  # negative_ratio | competitor_move | policy_change
    summary: str  # 一句话摘要，进简报与事件 payload
    negative_ratio: float = 0.0  # 仅 negative_ratio 类：当前负面占比 [0,1]
    baseline_ratio: float = 0.0  # 仅 negative_ratio 类：历史基线负面占比 [0,1]
    is_major: bool = False  # 仅 competitor_move 类：是否重大动作


@dataclass(frozen=True, slots=True)
class SentimentAlert:
    """一条命中的舆情告警（进事件 payload，往下推简报/提案/定向转发链）。"""

    channel: str
    kind: str  # negative_spike | competitor_move | policy_change
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        """JSON 安全序列化（进 outbox payload，往返无损）。"""
        return {
            "channel": self.channel,
            "kind": self.kind,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class SentimentThresholds:
    """检测阈值（**由调用侧经 runtime_config 注入，本域不硬编码**）。

    这里的字段默认只是「调用侧未配置时的安全回落值」——是校准旋钮而非业务真值，
    真实阈值走 sys_config/.env（见 sentiment_scanner._load_thresholds）。
    """

    negative_ratio_jump: float = 0.2  # 负面占比较基线突增达此幅度即命中
    negative_ratio_floor: float = 0.3  # 且当前负面占比不低于此（滤小样本噪声）
    competitor_major: bool = True  # 竞品「重大」动作是否告警
    policy_change: bool = True  # 政策变动是否告警
