# Token 优化策略

> 核心思路：局部思考 + 全局记忆引用，不让每个 session 全量思考。

---

## 问题诊断

每个 session 的 4 大浪费：

| 浪费点 | 估计浪费率 | 优化手段 |
|--------|-----------|---------|
| 重复加载项目结构 | 10–15% | 中央知识缓存（MCP 记忆） |
| 完整历史对话 | 10–15% | 提前压缩 + 任务隔离 |
| compaction 后残留无效 token | 5–10% | 精简 CLAUDE.md + 按需加载 |
| diff 修改带完整文件 | 5–10% | 局部文件加载 + Edit 代替 Write |

合计浪费率：30–50%。优化后理论可降 40–50%。

---

## 四个优化层

### 1. 中央知识缓存（降 15%）

**现状**：每个 session 都 Read 项目结构、grep 代码、探索模块关系。

**改法**：
- MCP 记忆已有，但使用不够激进 — 不只存"决策"，还要存"代码结构快照"
- 每次里程碑完成后，更新 `docs/CODE_MAP.md` 的模块摘要（函数签名 + 职责一句话）
- 新 session 开局：读 CLAUDE.md + CODE_MAP → MCP search 当前任务关键词 → 直接定位文件，跳过探索

**规则**：
- 禁止新 session 做全量 `Glob **/*.py` 探索，先查 CODE_MAP
- CODE_MAP 过期（上次更新 >2 个里程碑前）→ 先更新再干活

### 2. 文件级局部加载（降 10%）

**现状**：Read 整个文件 → 改 3 行 → 大量无关代码进了上下文。

**改法**：
- Read 时带 `offset` + `limit`，只读相关函数段（先 Grep 定位行号）
- 子 agent prompt 里只附被测函数源码，不附整个模块
- Write 改 Edit：能 Edit 就不 Write，避免完整文件重写

**规则**：
- 文件 >200 行 → 必须先 Grep 定位再局部 Read，禁止全量 Read
- 子 agent prompt 附源码 ≤150 行，超过就拆

### 3. 任务分层隔离（降 10%）

**现状**：一个 session 又做架构又写代码又跑测试，上下文越滚越大。

**改法**：按三层金字塔分 session 职责：

| session 类型 | 职责 | 需要的上下文 |
|-------------|------|-------------|
| 架构 session | 设计、决策、规划 | CLAUDE.md + CODE_MAP + specs |
| 执行 session | 写代码、改文件 | 当前模块源码 + TDD + checklist |
| 测试 session | 跑 pytest/ST、写测试 | 被测模块 + conftest + 测试范例 |

**规则**：
- 执行 session 不需要带全局历史，只带当前任务的 TDD 和相关文件
- 架构 session 的产出（TDD/设计文档）写入文件，执行 session 从文件读取
- 对话是传输层，文件是持久层 — 跨 session 信息必须走文件

### 4. 提前压缩 + 精简常驻 prompt（降 10%）

**现状**：CLAUDE.md 93 行 6KB，每条消息都带。checklist 按需读但经常全读。

**改法**：
- CLAUDE.md 保持精简，只放路由规则（"什么时候读什么文件"），不放具体 checklist 内容
- checklist 内容留在各自文件里，按任务类型按需加载一次
- claude-progress.txt 只保留最近 2 个里程碑的活动，历史归档到 changelog

**规则**：
- CLAUDE.md 硬限 100 行（当前 93 行，已接近上限）
- claude-progress.txt "最近活动"只保留最近 2 个日期段，更早的移到 changelog
- 子 agent 不读 CLAUDE.md（它们不需要流程规则，只需要任务指令）

---

## 执行 checklist

新 session 开局时：

1. [ ] 读 CLAUDE.md（自动）+ CODE_MAP（手动，<30s）
2. [ ] MCP search 当前任务关键词（查历史决策和踩坑）
3. [ ] 定位相关文件（从 CODE_MAP，不做全量探索）
4. [ ] 按任务类型读对应 checklist（只读一个，不全读）

子 agent 派发时：

1. [ ] prompt 只附相关源码片段（≤150 行）
2. [ ] 不传 CLAUDE.md / 流程规则给子 agent
3. [ ] 附一个范例文件当 few-shot（测试/实现风格参考）

里程碑完成时：

1. [ ] 更新 CODE_MAP（模块摘要）
2. [ ] claude-progress.txt 归档旧活动到 changelog
3. [ ] MCP 记忆存关键决策和踩坑

---

## 预期效果

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 每 session 探索开销 | 高（全量 grep/glob） | 低（CODE_MAP 直达） |
| 子 agent 上下文 | 完整文件 | 局部片段 ≤150 行 |
| 跨 session 重复工作 | 30–50% | <10%（MCP 缓存） |
| CLAUDE.md 膨胀风险 | 持续增长 | 硬限 100 行 |