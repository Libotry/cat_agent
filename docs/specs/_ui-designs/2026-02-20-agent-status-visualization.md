# UI 设计稿：Agent 状态可视化（F35）

> 生成时间：2026/2/20
> 阶段：开发流程阶段 2.5

---

## 变更范围

AgentStatusPanel 组件中的状态圆点和活动文案，支持新的三态模型（IDLE / THINKING / EXECUTING）+ PLANNING。

---

## 1. 组件结构

```
AgentStatusPanel/
  └── agent-status-item/  (每个 agent 一行，已有)
      ├── agent-status-avatar/
      │   ├── UserAvatar (32px，已有)
      │   └── agent-status-dot (14px 圆点，**本次改动**)
      ├── agent-status-info/
      │   ├── agent-status-name (已有)
      │   └── agent-status-activity (**文案逻辑变更**)
      └── agent-status-credits (已有)
```

不新增组件，只改已有组件的样式和逻辑。

---

## 2. 状态圆点颜色映射

| 状态 | CSS 变量 | 色值（civitas 主题） | 动画 | 语义 |
|------|----------|---------------------|------|------|
| idle | `--status-online` | #4caf50 (绿) | 无 | 空闲可用 |
| thinking | `--color-warning` | #f0b232 (琥珀) | pulse 1.5s | LLM 推理中 |
| executing | `--status-busy` | #ff9800 (橙) | pulse 0.8s（更快） | 执行动作中 |
| planning | `--func-purple` | rgb(130,60,120) (紫) | pulse 1.5s | 规划策略中 |
| offline | `--status-offline` | #999 (灰) | 无 | 离线 |

---

## 3. 脉冲动画规格

```css
@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
```

- thinking / planning: `animation: pulse-dot 1.5s ease-in-out infinite`
- executing: `animation: pulse-dot 0.8s ease-in-out infinite`（更快节奏表示正在执行）
- idle / offline: 无动画

---

## 4. 活动文案规则

| 状态 | 显示文案 | 来源 |
|------|---------|------|
| thinking | `agent.activity` 或 "思考中…" | WebSocket `agent_status_change` |
| executing | `agent.activity` 或 "执行中…" | WebSocket `agent_status_change` |
| planning | `agent.activity` 或 "规划中…" | WebSocket `agent_status_change` |
| idle | "空闲" | 固定文案 |
| offline | "离线" | 固定文案 |

文案样式不变：`font-size: 0.75rem; color: var(--text-muted)`

---

## 5. 排序规则

活跃状态排前面：executing > thinking > planning > idle > offline

---

## 6. 关键 CSS 片段

```css
/* 已有 — 不变 */
.agent-status-dot { /* 14px 圆点，absolute 定位 */ }
.agent-status-dot.idle { background: var(--status-online); }
.agent-status-dot.offline { background: var(--status-offline); }

/* 新增 */
.agent-status-dot.thinking {
  background: var(--color-warning);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

.agent-status-dot.executing {
  background: var(--status-busy);
  animation: pulse-dot 0.8s ease-in-out infinite;
}

.agent-status-dot.planning {
  background: var(--func-purple);
  animation: pulse-dot 1.5s ease-in-out infinite;
}

@keyframes pulse-dot {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
```

---

## 7. 交互状态

- hover: 无变更（已有 agent-status-item hover 样式）
- empty: 无变更（agent 列表为空时已有处理）
- loading: 无变更（初始加载时 agent 列表为空，显示后立即有状态）

---

## 8. 验收标准（供阶段 6.5 使用）

- [ ] idle 状态圆点为绿色（`--status-online` = #4caf50），无动画
- [ ] thinking 状态圆点为琥珀色（`--color-warning` = #f0b232），有 1.5s 脉冲动画
- [ ] executing 状态圆点为橙色（`--status-busy` = #ff9800），有 0.8s 脉冲动画（比 thinking 更快）
- [ ] planning 状态圆点为紫色（`--func-purple` = rgb(130,60,120)），有 1.5s 脉冲动画
- [ ] offline 状态圆点为灰色（`--status-offline` = #999），无动画
- [ ] 活动文案区域显示对应状态的中文描述，字号 0.75rem，颜色 `--text-muted`
- [ ] 列表排序：executing 排最前，其次 thinking、planning、idle、offline
- [ ] 所有颜色使用 CSS 变量，无硬编码色值
- [ ] 脉冲动画流畅，无卡顿（opacity 0.4 ↔ 1.0）
