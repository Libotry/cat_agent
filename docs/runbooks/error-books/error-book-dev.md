# 错题本 — 💻 开发者

> 按需加载：先读 `_index.md` 速查索引，再按模块读对应文件。

### 记录规则

- **DEV-BUG 条目只写摘要**（场景/根因/修复/防范，各 1-2 行），控制在 10 行以内
- **详细复盘**放独立文件 `postmortem-dev-bug-N.md`，错题本里放链接
- **目的**：每次只加载需要的子文件，控制 token 消耗

---

## 子文件索引

| 分类 | 文件 | 覆盖范围 |
|------|------|---------|
| 速查索引 | [_index.md](_index.md) | 全部条目一句话索引（每次必读） |
| 通用/流程 | [flow-rules.md](flow-rules.md) | 门控、CR、归零等流程纪律（每次必读） |
| 通用/工具 | [tool-rules.md](tool-rules.md) | Write、Bash、curl、Playwright 等工具技巧 |
| 接口协作 | [interface-rules.md](interface-rules.md) | 前后端协作、API 契约、类型对齐 |
| 后端/Agent | [backend-agent.md](backend-agent.md) | Agent 唤醒、LLM、WebSocket、Plugin |
| 后端/DB | [backend-db.md](backend-db.md) | SQLite、测试 fixture 隔离 |
| 后端/API+环境 | [backend-api-env.md](backend-api-env.md) | API 路由、参数校验、Windows 环境 |
| 前端/UI | [frontend-ui.md](frontend-ui.md) | 组件、样式、主题、可访问性 |
| 前端/React | [frontend-react.md](frontend-react.md) | hooks、状态管理、StrictMode |
