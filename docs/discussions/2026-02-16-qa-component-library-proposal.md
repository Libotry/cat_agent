# M2.2 前端组件库选型 — QA Lead 方案

**日期**: 2026-02-16
**角色**: 🧪 QA Lead
**议题**: 替代手写主题系统，消除配色硬编码

---

## 方案：Radix UI + CSS 变量清理（渐进式迁移）

### 核心思路

从可测试性和回归风险出发，优先保护现有测试资产（14/14 E2E + 23 组件 UT），采用**最小改动面**策略：

1. **交互组件用 Radix Primitives 包装**（Dropdown、Dialog、Tooltip 等），不改现有组件结构
2. **CSS 变量系统保留**，themes.css 继续作为单一真相源
3. **分阶段迁移**：先迁移 1-2 个高风险组件（如 ChatInput 的 @提及弹窗），验证测试兼容性后再推广

---

## 核心优势

### 1. 测试兼容性最高（E2E 选择器基本不变）

- **现状**：E2E 用 `className` 选择器（如 `.msg-row`, `.channel-item`），组件 UT 用 `getByText` / `getByRole`
- **Radix 影响**：只在交互组件外包一层 `<Dropdown.Root>`，DOM 结构微调，现有选择器 90% 不受影响
- **shadcn/ui 风险**：会重写组件内部结构（如 MessageBubble 改用 `<Card>` + Tailwind），E2E 选择器大面积失效

**测试改动量对比**：
- Radix UI：预计 2-3 个 E2E 用例需微调（弹窗相关）
- shadcn/ui：预计 10+ 个 E2E 用例需重写（所有组件结构变化）

### 2. 回归风险可控（分阶段验证）

- **Phase 1**：迁移 ChatInput @提及弹窗（1 组件，高风险区），跑 E2E 验证无回归
- **Phase 2**：迁移 BountyBoard 筛选下拉（1 组件），验证表单交互
- **Phase 3**：推广到其他组件
- **每个 Phase 都有测试门禁**：UT 全绿 + E2E 全绿才进入下一阶段

### 3. 保留现有主题系统（避免双主题验证流程重建）

- **themes.css 159 行 CSS 变量**是经过 DEV-BUG-11 修复后的稳定资产，已覆盖双主题场景
- Radix UI 无样式，直接用现有 CSS 变量，不引入新的主题抽象层
- **DEV-8 流程不变**：新增 UI 仍然切换主题验证，颜色仍然只用 CSS 变量

### 4. 无障碍性开箱即得（Radix 内建 ARIA）

- Radix Primitives 自带键盘导航、焦点管理、屏幕阅读器支持
- 减少手写交互组件的无障碍测试负担（当前 ChatInput 弹窗无键盘导航）

---

## 已知不足（诚实承认）

### 1. 依赖增加（但比 shadcn/ui 少）

- Radix UI 会引入 ~10 个包（@radix-ui/react-dropdown-menu 等），但无 Tailwind 全家桶
- 包体积：Radix ~50KB gzipped，shadcn/ui + Tailwind ~150KB+

### 2. 不解决"组件代码冗余"问题

- 现有 11 组件 523 行代码，Radix 只优化交互部分，布局代码仍需手写
- shadcn/ui 的 `<Card>` / `<Badge>` 等布局组件能减少重复代码，但代价是大面积重写

### 3. 学习曲线（Radix 的组合式 API）

- Radix 用 `<Dropdown.Root>` + `<Dropdown.Trigger>` + `<Dropdown.Content>` 组合，比单组件复杂
- 团队需要熟悉 Radix 的 Composition 模式

---

## 想向其他专家请教的问题

### 给 Tech Lead

1. **依赖管理**：Radix UI 的 ~10 个包是否会增加构建复杂度？Vite 的 tree-shaking 能否有效减少最终包体积？
2. **TypeScript 兼容性**：Radix 的泛型组件（如 `<Select<T>>`）是否会与现有类型系统冲突？

### 给前端开发

3. **CSS 变量映射**：Radix 组件的 data-state 属性（如 `[data-state="open"]`）如何与现有 CSS 变量系统对接？是否需要额外的 CSS 适配层？
4. **动画过渡**：当前主题无动画，Radix 的弹出动画是否需要禁用以保持一致性？

### 给架构师

5. **长期演进**：如果未来要引入设计系统（如 Cat Cafe 风格），Radix + CSS 变量的架构是否足够灵活？还是应该现在就上 shadcn/ui 一步到位？

---

## 测试策略（如果采纳此方案）

### Phase 1 验收标准

- [ ] ChatInput @提及弹窗迁移到 Radix Dropdown
- [ ] 23 个组件 UT 全绿（无新增失败）
- [ ] 14 个 E2E 场景全绿（允许微调选择器，但不能删减覆盖）
- [ ] 双主题验证通过（civitas + dark）
- [ ] 键盘导航测试：Tab / Enter / Esc 能正确操作弹窗

### 回归测试清单

每次迁移一个组件后必跑：
1. `npm run test` — 组件 UT
2. `python server/e2e_phase6.py` — 后端 E2E（确保 API 交互不受影响）
3. 手动双主题切换验证（DEV-8 流程）
4. 键盘导航冒烟测试（Tab 遍历所有交互元素）

---

**总结**：从质量视角，Radix UI 是"最不会让测试全部重写"的方案，适合当前"测试资产已建立、需要稳步优化"的阶段。如果团队愿意承担更大的重构成本换取长期收益，shadcn/ui 也是合理选择，但需要预留 2-3 天重写测试用例。
