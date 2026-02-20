# M6 Phase 1 SR — 策略自动机最小验证

> 状态：SR 已确认 | 五方评审完成

## 目标

用 ~1 天验证"战略游戏 AI 两层架构"是否可行。只做 2 种策略类型：`keep_working` + `opportunistic_buy`。

**验证成功标准**：keep_working 和 opportunistic_buy 各跑通一个端到端场景，策略自动执行且终止条件生效。

## 已确认的设计约束

- 策略格式极简扁平，不嵌套
- LLM 输出解析失败 → 退化为现有单次 action 模式
- 保留 hourly tick，策略自动机在 hourly tick 内执行（Phase 1 不做独立 60 秒 tick）
- 现有 autonomy_service 的 action 执行逻辑完全复用
- 策略存储：内存 dict，每次 hourly tick LLM 输出新策略直接全量覆盖旧策略，不持久化
- 策略生命周期：全量覆盖 = 自动清理，终止条件达成的策略在执行时跳过

## Phase 1 范围

### 策略类型 1：keep_working

Agent 说"持续在农田工作直到小麦达到 50"，自动机自动执行 checkin。

```json
{"agent_id": 1, "strategy": "keep_working", "building_id": 3, "stop_when_resource": "wheat", "stop_when_amount": 50}
```

### 策略类型 2：opportunistic_buy

Agent 说"小麦粉低于 1.5 就买"，自动机扫描市场挂单自动接单。

```json
{"agent_id": 1, "strategy": "opportunistic_buy", "resource": "flour", "price_below": 1.5, "stop_when_amount": 20}
```

## Go/No-Go 关卡

**在写引擎之前，先验证 LLM 输出质量：**
1. 写好策略 pydantic schema
2. 改 SYSTEM_PROMPT，加 few-shot 示例
3. 手动跑 5-10 轮 LLM，统计策略 JSON 输出成功率
4. 成功率 >= 70% → Go，继续实现引擎
5. 成功率 < 70% → 简化 schema 或换模型，再测一轮
6. 仍然不行 → No-Go，退回现有 action 模式

## 任务列表（按执行顺序）

### 阶段 A：Schema + Prompt 验证（Go/No-Go）

| # | 任务 | 依赖 | 预估 |
|---|---|---|---|
| T1 | 策略数据模型：pydantic schema + 内存存储 + 生命周期（全量覆盖） | 无 | 0.5h |
| T2 | SYSTEM_PROMPT 改造：输出策略格式 + few-shot 示例 | T1 | 1h |
| T3 | decide() 返回值改造 + JSON schema 校验 + fallback 退化 | T1 | 1h |
| T2T3 可并行 | | | |
| T4 | 手动验证：跑 5-10 轮 LLM，统计输出成功率 | T2+T3 | 0.5h |

**T4 通过后进入阶段 B。**

### 阶段 B：引擎实现

| # | 任务 | 依赖 | 预估 |
|---|---|---|---|
| T5 | action 执行函数抽取：从 execute_decisions 的 if/else 中抽出独立函数 | 无（可与阶段 A 并行） | 1h |
| T6 | 策略引擎核心：条件匹配 + 执行 + 终止检查 | T1+T5 | 2h |
| T7 | hourly tick 集成：tick() 改为"LLM 更新策略 → 自动机匹配执行" | T3+T6 | 1h |
| T8 | 观测 API：GET /api/agents/{id}/strategies 查看当前策略 | T1 | 0.5h |

### 阶段 C：测试

| # | 任务 | 依赖 | 预估 |
|---|---|---|---|
| T9 | 单元测试：策略引擎条件匹配（keep_working + opportunistic_buy） | T6 | 1h |
| T10 | 集成测试 + ST：端到端验证 | T7 | 1h |

## 依赖图

```
T1 ──→ T2 ──┐
  │         ├──→ T4 (Go/No-Go) ──→ T7 ──→ T10
  └──→ T3 ──┘                       ↑
                                     │
T5 ──→ T6 ──────────────────────────┘
  │         ↑
  │         T1
  └──→ T8
       T9 (跟 T6 并行写，TDD)
```

## 五方评审记录

### 遗漏项（已补充）
- 策略生命周期管理 → 合并到 T1，全量覆盖策略
- 观测手段 → 新增 T8，GET API 查看当前策略
- action 执行函数抽取 → 新增 T5
- Phase 1 不需要独立 60 秒 tick（Tech Lead 提出），在 hourly tick 内执行

### 最高风险共识
5/5 一致：PROMPT + decide 改造（T2+T3）是成败关键，必须先验证 LLM 输出质量

### fallback 策略
- 任务 6 合并到 T3（本质是 decide() 的一部分）
- PM 强调：先保证能回退，再往前冲
