# 错题本 — 后端/DB

### 记录规则

- **DEV-BUG 条目**：场景/根因/修复，各 1 行，控制在 **6 行以内**
- 详细复盘放 `../postmortems/`，这里只放链接

### DEV-10 SQLite + async 必须用 BEGIN IMMEDIATE `🟢`

❌ 默认 `BEGIN DEFERRED`，多连接同时持有 SHARED 锁升级时死锁；fire-and-forget 写入是反模式
✅ 用 `BEGIN IMMEDIATE` 事件监听器，合并写入到同一事务；不要用 asyncio.Lock 序列化 aiosqlite
> 案例：DEV-BUG-7。详见 [postmortem-dev-bug-7.md](../postmortems/postmortem-dev-bug-7.md)

### DEV-10c E2E 测试 fixture 只 create_all 不先 drop_all → UNIQUE 冲突 `🟢`

❌ `setup_db` 用 `Base.metadata.create_all` 但不先清理，生产 DB 已有数据时 seed 插入冲突
✅ fixture 先 `drop_all` 再 `create_all`，保证每个测试从空表开始
> 测试隔离是基本功。create_all 对已存在的表是 no-op，不会清数据。

#### DEV-BUG-2 httpx ASGITransport 不触发 lifespan `🟢`

- **场景**: 用 httpx + ASGITransport 跑 FastAPI 测试
- **现象**: `no such table` 报错
- **原因**: ASGITransport 不触发 FastAPI lifespan，表没建
- **修复**: 测试 fixture 手动 `Base.metadata.create_all` + `ensure_human_agent`

#### DEV-BUG-7 SQLite 并发锁定导致测试死循环（耗时 2h+，200 刀） `🟢`

- **场景**: M2 Phase 1 完整测试，多个 async task 同时写 SQLite
- **根因 & 修复**: 见流程规则 DEV-10
- **详细复盘**: [postmortem-dev-bug-7.md](../postmortems/postmortem-dev-bug-7.md)
