# ADR-019：Lodge resource-server 基础

Lodge 集成默认关闭，并保持现有 HS256 登录和 `get_current_user` 不变。新模块只验证
`lodge_identity_v2` 的 RS256、`typ=at+jwt`、`token_use=access`、`token_profile=user`、单一
`aud=youdoogo` target token；JWKS 与 online status 均受超时、大小限制和 fail-closed 约束。

Lodge status 使用独立的 `LODGE_STATUS_SERVICE_TOKEN` 发起 POST JSON，且只依据已验证的
`sub`、`sid`、`jti`、`org_id`、`identity_ver` 复核 active/version/session/entitlement 及回显的
`subject`/`system_key`。客户端自报的角色、部门或权限不进入 principal；status scope 只构成上限，
决策云仍是本地业务 ACL 的唯一判定者。

浏览器 token 仅用于本服务的身份验证，绝不得转发至 `llm_api`、`llm_wiki` 或任何下游。未来的
下游调用须使用单独的服务凭证或受控 delegated-token exchange（不属于本切片）。
