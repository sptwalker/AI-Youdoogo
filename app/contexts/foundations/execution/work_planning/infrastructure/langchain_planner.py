"""LangChain adapter for the Work Planning model port."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.contexts.foundations.execution.work_planning.contracts.planning import WorkIntent

PLANNER_SYSTEM = (
    "你是任务编排规划器。判断用户请求是否是「需要多个有序步骤」的复合任务。"
    "只输出 JSON，不要任何解释或代码块标记。\n"
    '格式:{"multi": bool, "steps": [{"no": int, "title": str, "skill": str, '
    '"instruction": str, "depends_on": [int]}]}\n'
    "- multi=false 表示单一动作（普通问答/单步），此时 steps 给空数组。\n"
    "- skill 只能取:data_query(查运营数据)、deliver(生成文件/文档/表格)、"
    "collab(联系其他部门/AI)、notify(通知某真人)、other(其它)。\n"
    "- no 从 0 开始递增;depends_on 填本步依赖的前序步骤 no 列表（无依赖=空数组）。\n"
    "- instruction 用一句话说清这步要做什么。步骤按依赖排序，最多 8 步。\n"
    "示例请求「把昨天运营数据做成日报并通知运营总监」→"
    '{"multi":true,"steps":[{"no":0,"title":"取昨日运营数据","skill":"data_query",'
    '"instruction":"查询昨天各产品运营指标","depends_on":[]},'
    '{"no":1,"title":"生成运营日报","skill":"deliver","instruction":"把数据做成日报文档",'
    '"depends_on":[0]},{"no":2,"title":"通知运营总监","skill":"notify",'
    '"instruction":"把日报通知运营总监","depends_on":[1]}]}'
)


class LangChainPlanningModelAdapter:
    def __init__(self, llm_factory: Callable[..., Any]) -> None:
        self._llm_factory = llm_factory

    async def propose(self, intent: WorkIntent) -> str:
        llm = self._llm_factory("reasoning", temperature=0.0)
        reply = await llm.ainvoke(
            [
                SystemMessage(content=PLANNER_SYSTEM),
                HumanMessage(content=f"用户请求:{intent.request.strip()}"),
            ]
        )
        return reply.content if isinstance(reply.content, str) else str(reply.content)
