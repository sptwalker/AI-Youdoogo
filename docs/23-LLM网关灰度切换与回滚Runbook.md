# 23-LLM 网关灰度切换与回滚 Runbook

> docs/21《通用AI平台拆分架构与落地方案》Phase 1 的**操作配套**。面向发布/运维。
> 前置架构与契约见 docs/21 §7.1/§8.1/§9、docs/09《模型网关设计》。

## 0. 结论先行

- 客户端半边 `RemoteLlmAdapter` 与网关服务两半边**已跨仓真互通验证**（真 socket、真 JWT
  签发→验签、chat/SSE 线协议逐字对齐、鉴权边界 4xx 拒绝）。切换是安全的。
- **路线 A（终态）**：远程为主、本地为**永久安全网**。命中远程时经 `FallbackCompletionPort`
  包裹，远程失败静默降级本地。故 **无「切换后删业务密钥」步骤**——`LocalLlmAdapter` 与业务厂商
  卡片永久保留。docs/21 原步骤 7 在路线 A 下永久退役。
- 切换 = **只改部署 env / sys_config，不改代码默认值**（`llm_completion_mode` 代码默认恒 `local`，
  保护未配置环境）。

## 1. 前置：部署网关服务（真环境，非本地 stub）

| 项 | 要求 |
|---|---|
| ES256 密钥对 | 私钥**只**留 AI-Youdoogo（`INTERNAL_JWT_PRIVATE_KEY`）；公钥给网关（`INTERNAL_JWT_PUBLIC_KEY`）。**网关绝不持私钥**（docs/21 §9 红线） |
| iss / aud | 两侧一致：`iss=youdoogo-platform`、`aud=ai-model-gateway`（均为默认，勿改错） |
| 模型卡 | 网关 `GATEWAY_CARDS` 种真 chat 卡（DeepSeek 主力档 daily）+ 真 `DATABASE_URL`（生产 `postgresql+asyncpg://...`） |
| 存活探针 | `GET /healthz` 返 `{"status":"ok","cards":N}`，N>0 |

生成密钥对：
```bash
openssl ecparam -genkey -name prime256v1 -noout -out es256-private.pem   # → AI-Youdoogo
openssl ec -in es256-private.pem -pubout -out es256-public.pem           # → 网关
```

⚠️ **卡片 gotcha**：网关 `init_cards()` **首启**把 `GATEWAY_CARDS` 种入 DB，**之后只读 DB、忽略
env**。生产改卡走 DB（改 `ai_provider` 表 active 卡后重启），**不是**改 env 重启。换库调试可换新
`DATABASE_URL`。

## 2. 灰度开阀（AI-Youdoogo 侧，改部署 env / sys_config）

```
LLM_COMPLETION_MODE=remote
LLM_GATEWAY_URL=https://<网关内网地址>
LLM_GATEWAY_CANARY_PERCENT=1        # 抽样比例：1 → 10 → 50 → 100，逐级观察后再升
```

- `PERCENT=0` 或 `MODE=local` → 全走本地（生产默认，安全）。
- `0<PERCENT<100` → 每次调用按概率落远程/本地；命中远程仍带本地兜底。
- `PERCENT=100` → 全部尝试远程、失败兜底本地（路线 A 终态）。

## 3. 每级放量的观察指标

| 指标 | 看什么 |
|---|---|
| 成功率 / 时延 | 远程路径是否与本地基线持平 |
| token / 成本 | 网关记账（`usage` 表）与预期一致 |
| **fallback 激活数** | 日志 `WARN … 降级本地 model_role=…`（invoke / stream 首块前失败）。**持续偏高 = 远程不稳，停止升级、先排障** |
| 配额 | 网关 `llm_daily_token_budget` 命中则 429（当日硬限） |

放量判据：某级稳定（fallback≈0、成功率/成本达标）→ 升下一级；否则回滚排障。

## 4. 回滚（一步，秒级）

```
LLM_GATEWAY_CANARY_PERCENT=0        # 或 LLM_COMPLETION_MODE=local
```

- 立即全量回本地，无需重部署网关、无需删任何 key。
- 路线 A 下本地是永久安全网，**无「回滚窗口终止后删 Secret」动作**。

## 5. 红线自检（每次发布必过）

- [ ] 网关侧无私钥，只有公钥
- [ ] 日志无 Authorization / body 明文（§7.1）
- [ ] AI-Youdoogo 代码内 `llm_completion_mode` 默认仍为 `local`（切换只在 env）
- [ ] 缺/错令牌被网关 4xx 拒绝

## 6. 互通自检（可选，切换前想复验时）

两半边真互通可用**测试专用**密钥对离线复跑：网关注入 stub provider + 测试公钥起服务，
AI-Youdoogo 侧用测试私钥签令牌打真 socket，断言 chat/SSE 字段与鉴权边界。密钥/脚本全放临时目录，
**不落库、不入 .env、不提交**。（本轮已跑通并清理；需要固化为脚本再单独增量。）
