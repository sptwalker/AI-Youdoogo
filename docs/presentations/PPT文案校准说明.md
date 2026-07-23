# PPT 文案校准说明

## 校准原则

本次文案只使用三类口径：

1. **目标规范**：来自 `docs/20-DDD领域边界与分层架构规范.md`。
2. **当前实现**：来自当前服务代码、状态机和测试可验证的行为。
3. **目标接续**：文档要求但当前代码尚未自动打通的业务链路。

## 关键修正

- 不再把四层运行架构、DDD Context 和代码依赖层混为一张图。
- 不再把运行角色画成独立 Context，也不再把中枢编排画成万能服务。
- 真人任务从能力执行门禁中拆出，由任务管理承担其生命周期。
- 上下文系统改为统一受治理读取与快照装配入口，不再表达为所有 Context 共写的共享数据库。
- 反馈只形成候选改进，必须经评估、必要审批和版本发布，不能直接修改生产配置。
- 运营分析明确区分“当前只能生成建议文本”和“目标上由正式业务用例创建提案/任务”。
- 提案页删除不存在的“AI 审校业务状态”，按 `draft → researching → reviewed → approved/rejected` 表达。
- 会议页拆开真实前置条件：讨论/投票要求进行中，纪要要求已有发言，创建决议只校验会议存在。
- 明确 `human_passed` 只是统计值；只有真人确认后的决议才能转换一次任务卡。
- DDD 分类页将任务管理、能力执行放回 Foundation Context，将 MCP 传输和 LLM SDK 放入 Platform。

## 主要事实源

- 架构与边界：`docs/20-DDD领域边界与分层架构规范.md`
- 运营分析：`app/agents/ops.py`、`app/contexts/business/operational_analytics/entrypoints/agent_operations.py`
- 提案管理：`app/contexts/business/proposal_management/entrypoints/operations.py`
- 会议管理：`app/contexts/business/meeting_management/entrypoints/operations.py`
- 任务状态机：`app/services/task_flow.py`
