# ADR-0010：Lodge resource-server 基础

Lodge 集成默认关闭，并保持现有 HS256 登录和 `get_current_user` 不变。新模块只验证
`lodge_identity_v2` 的 RS256、`typ=at+jwt`、`token_use=access`、`token_profile=user`、单一
`aud=youdoogo` target token；JWKS 与 online status 均受超时、大小限制和 fail-closed 约束。

Lodge status 使用独立的 `LODGE_STATUS_SERVICE_TOKEN` 发起 POST JSON，且只依据已验证的
`sub`、`sid`、`jti`、`org_id`、`identity_ver` 复核 active/version/session/entitlement 及回显的
`subject`/`system_key`。客户端自报的角色、部门或权限不进入 principal；status scope 只构成上限，
决策云仍是本地业务 ACL 的唯一判定者。

`LODGE_STATUS_CACHE_MAX_ENTRIES` 对 status 缓存设置硬上限。每次读取和插入都清理过期项；满额时
按最早到期时间、再按完整缓存 key 确定性驱逐。缓存 key 保持 `sub/sid/org/version/jti`，因此任何
缓存驱逐都只会促成一次新的 fail-closed status 请求，绝不因缓存已满放过 status 验证。

`Settings` 在开关开启时即验证远端 URL、audience、超时、TTL、响应大小、缓存容量与服务凭证，避免把
不安全配置推迟到 service 构造或首个请求。配置模板只提供非敏感默认值和空 Secret 占位。

生产 HTTP client 的所有权属于调用 `service_from_settings` 的 composition root：它必须在应用 shutdown
时调用 `AsyncClient.aclose()`。`LodgeIdentityService`、JWKS client 和 status client 从不自行关闭注入的
client。测试通过 fixture 集中关闭每个 `AsyncClient`，以匹配这一所有权契约。

跨仓契约固定在 `tests/contracts/lodge_identity_v2_youdoogo.json`：它从 Lodge `51b73fa` 的最终 handoff、
target-token 和 identity-status handler 事实抽取，包含版本、JWT、status、cookie 和 scope ceiling。测试
只读取该仓内静态 fixture；这不是 staging 联调声明，也不引入运行期跨仓依赖。

浏览器 token 仅用于本服务的身份验证，绝不得转发至 `llm_api`、`llm_wiki` 或任何下游。未来的下游调用须
使用单独的服务凭证或受控 delegated-token exchange（不属于本切片）。
