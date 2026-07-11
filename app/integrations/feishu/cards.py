"""飞书交互式卡片构建纯函数。

移植自 feishu_project_manager 并做减法：只保留通用构建器，
业务专属卡片（任务/风险/周会等）阶段2按需加。
返回的字典可直接作为 interactive 消息的 content 发送。
"""

from typing import Any

# 卡片头部颜色模板（飞书内置）
HEADER_BLUE = "blue"
HEADER_GREEN = "green"
HEADER_ORANGE = "orange"
HEADER_RED = "red"
HEADER_GREY = "grey"


def build_notification_card(
    title: str, lines: list[str], header_template: str = HEADER_BLUE
) -> dict[str, Any]:
    """构建通用通知卡片。

    Args:
        title: 卡片标题。
        lines: 正文行（支持 lark_md 语法）。
        header_template: 头部颜色模板。
    """
    content = "\n".join(lines) if lines else " "
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": header_template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": content}},
        ],
    }


def build_info_card(
    title: str, fields: dict[str, Any], header_template: str = HEADER_BLUE
) -> dict[str, Any]:
    """构建「标题 + 字段列表」的简单信息卡片。

    Args:
        title: 卡片标题。
        fields: 字段名到字段值的映射，逐行渲染为 **字段名**：值。
        header_template: 头部颜色模板。
    """
    lines = [f"**{k}**：{v}" for k, v in fields.items()]
    return build_notification_card(title, lines, header_template)
