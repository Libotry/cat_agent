# Postmortem DEV-38: 编码前跳过 AR → 安全/异常/配置全面失守

## 场景

M6 Phase 2 上网工具（web_search / web_fetch）编码完成后，独立 CR 一次性发现 P0×4 + P1×7 + P2×7 = 18 个问题。

## 问题清单

| 级别 | 编号 | 问题 |
|------|------|------|
| P0 | P0-1 | SSRF TOCTOU — DNS 解析和实际连接是两次独立调用，存在 DNS rebinding 攻击窗口 |
| P0 | P0-2 | web_search 失败返回 `[]` 被当成功处理，照扣 credits |
| P0 | P0-3 | fetch 失败时 `return f"抓取失败: {e}"` 泄露内部异常信息（可能含 API key） |
| P0 | P0-4 | SSRF 错误信息回显用户输入的 URL，潜在 XSS + 信息探测 |
| P1 | P1-1 | `_BLOCKED_NETS` 缺 IPv6 私网段（fc00::/7、fe80::/10） |
| P1 | P1-2 | `_web_usage` 非协程安全，多 worker 部署时限制失效 |
| P1 | P1-3 | 频率限制错误信息硬编码 "10 次"，不跟随配置 |
| P1 | P1-4 | `is_ssrf` 在 handler 和 provider 两层重复调用，加剧 TOCTOU |
| P1 | P1-5 | fetch 失败返回字符串而非抛异常，调用方无法区分成功/失败 |
| P1 | P1-6 | 缺"失败时不扣费"的测试 |
| P1 | P1-7 | 文档说"三级 fallback"但代码只用单一 Provider |
| P2 | P2-2 | timeout 硬编码 15 |
| P2 | P2-3 | UA 硬编码 "Mozilla/5.0" |
| P2 | P2-4 | snippet 截断 300 硬编码 |
| P2 | P2-5 | ST-3 SSRF 断言过于宽松（>= 199 而非 == 200） |
| P2 | P2-6 | ST 依赖 LLM 行为（已知限制） |
| P2 | P2-7 | pytest_asyncio 风格（不影响功能） |

## 根因分析

### 直接原因：编码前没写 AR

没有在编码前定义异常传播策略、安全检查层级、副作用时序、可配置项清单。直接开写，导致每个维度都是随手决策，互相矛盾。

### 为什么跳过 AR

旧规则认为"Opus 终端不需要 AR，直接编码即可"。这个假设在简单 CRUD 场景下成立，但上网工具涉及外部 HTTP 调用 + SSRF 防护 + 计费 + 频率限制，复杂度远超 CRUD，需要 AR 来统一架构决策。

### 具体失守维度

1. **安全**（P0-1/3/4）：写 SSRF 防护时只想到"检查 IP 是否在私网段"，没考虑 DNS rebinding。写错误返回时直接把内部异常原样暴露。缺乏"攻击者视角"的思维习惯。
2. **异常处理**（P0-2/P1-5）：Provider 层有的吞异常返回空列表，有的返回字符串，handler 层有的 catch ValueError 有的不 catch。没有统一的错误传播策略。
3. **副作用时序**（P0-2）：先扣费后调用外部服务，失败时 credits 已扣但用户没拿到结果。
4. **可配置性**（P1-3/P2-2/3/4）：timeout、UA、snippet 截断、频率消息全部硬编码 magic number。

## 修复

全部 18 条修复，经四轮独立 CR 归零。关键修复：

- P0-1：新增 `_SSRFSafeTransport`，TCP 连接前二次校验目标 IP
- P0-2/P1-5：Provider 层改为抛异常，handler 层统一 `except Exception`，失败不扣费
- P0-3/P0-4：错误消息改为固定中文，不暴露内部异常和用户输入
- P2-2/3/4：timeout/UA/snippet 提取到 config

## 防范 checklist

编码前 AR 必须覆盖以下四项（涉及外部调用的模块）：

1. **异常传播策略** — Provider 层抛异常 vs handler 层统一 catch，禁止 Provider 吞异常返回空值
2. **副作用时序** — 先调用后扣费，失败不扣费（乐观预检 + 悲观扣费）
3. **安全检查层级** — SSRF（含 DNS rebinding）、信息泄露（错误消息脱敏）、输入回显（不把用户输入放进错误消息）
4. **可配置项清单** — 零 magic number，所有运行时参数走 config
