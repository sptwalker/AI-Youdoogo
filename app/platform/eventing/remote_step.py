"""后台步骤异步远端执行的线协议常量（docs/23 §6.3）。

放在 platform.eventing（传输层）而非某个 Context，好让出站 relay、入站 http、runtime 分叉点
共用同一组字面量而不产生 platform→context 反向依赖（runtime 侧 import 本模块 = context→platform）。
"""

from __future__ import annotations

STEP_READY_EVENT = "workflow.step.ready.v1"  # youdoo→expert：步骤就绪、请远端执行
EXPERT_COMPLETED_EVENT = "expert.execution.completed.v1"  # expert→youdoo：执行完成、请唤醒停车 step
REMOTE_SENTINEL = "remote-expert"  # 停车 step 的 lease_owner；与真人停点(WAITING_HUMAN)天然可辨
