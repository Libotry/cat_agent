# M5.2 — 交易市场 需求拆分（SR）

> 挂单/接单/撤单 + autonomy_loop + Tool Use + 前端市场面板

---

## 前置条件

- AgentResource.quantity 需从 Integer 迁移为 Float（IR 原始设计为 Float 精度 0.01，M5 实施时用了 Integer，M5.2 需修正）
- 新增 AgentResource.frozen_amount（Float）字段，用于挂单冻结
- 新增 MarketOrder、TradeLog 数据表

---

## 任务分解

| ID | 任务 | 终端 | 依赖 | 状态 |
|----|------|------|------|------|
| M5.2-1 | DB 迁移（Float + frozen_amount + MarketOrder + TradeLog） | 后端 | — | pending |
| M5.2-2 | market_service.py（挂单/接单/撤单核心逻辑） | 后端 | M5.2-1 | pending |
| M5.2-3 | 市场 API（POST/GET/DELETE /api/market/orders） | 后端 | M5.2-2 | pending |
| M5.2-4 | autonomy_loop 集成（create_order + accept_order 动作） | 后端 | M5.2-2 | pending |
| M5.2-5 | Tool Use 注册（create_market_order + accept_market_order） | 后端 | M5.2-2 | pending |
| M5.2-6 | 前端交易市场面板（扩展现有 TradePage） | 前端 | M5.2-3 | pending |
| M5.2-7 | WebSocket 事件（order_created/order_traded/order_cancelled） | 后端 | M5.2-2 | pending |
| M5.2-8 | 端到端验证 | 集成 | M5.2-4, M5.2-5, M5.2-6 | pending |

---

## 关键路径

```
M5.2-1 → M5.2-2 → M5.2-3 → M5.2-6
                 → M5.2-4
                 → M5.2-5
                 → M5.2-7
```

---

## 验收标准

详见 [01-需求原型.md](../01-需求原型.md) 中 M5.2 的 AC-M5.2-01 ~ AC-M5.2-20。
