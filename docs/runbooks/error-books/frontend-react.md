# 错题本 — 前端/React

### DEV-9 useEffect 外部连接必须幂等 `🟢`

❌ useEffect 里直接 `new WebSocket()`，没考虑 StrictMode 双挂载导致重复创建
✅ 外部连接（WebSocket/SSE/EventSource）必须：cleanup 关旧连接 + 创建前检查已有连接 + 消息层去重
> React StrictMode 开发模式双挂载 effect，不做幂等 = 开发时必现重复。

### DEV-10 useEffect 依赖放 render 中新建的数组/对象 → 无限循环 `🟢`

❌ `const filtered = arr.filter(...)` 在 render 里算，然后放进 `useEffect([filtered])` — 每次 render 新引用 → 触发 effect → setState → 再 render
✅ 用 `useMemo` 稳定引用，或用 `.length` 等原始值做依赖
> 数组/对象每次 render 都是新引用。案例：M3 WorkPanel nonHumanAgents 无限循环。

### DEV-15 `_useMock` 单例缓存导致后端恢复后前端仍走 mock `🟢`

❌ `useMock()` 首次检查 `/api/health` 失败后 `_useMock = true` 被永久缓存，后端恢复后刷新页面也不重新检查
✅ 方案 A：每次 WS 连接失败时重置 `_useMock = null` 强制重新探测；方案 B：加 TTL；方案 C：去掉自动检测，改为显式 `?mock` 参数
> 根因：单例缓存 + 无过期机制。

#### DEV-BUG-10 React StrictMode 双挂载导致 WebSocket 消息重复 `🟢`

- **场景**: 开发模式下聊天消息每条显示两次
- **根因 & 修复**: 见流程规则 DEV-9
- **修复文件**: useWebSocket hook 加连接守卫 + DiscordLayout 加 msg.data.id 去重
