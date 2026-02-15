# OpenClaw Plugin 代码放置方案讨论

**日期**: 2026-02-14
**类型**: 协作讨论
**参与方**: 架构设计专家 / 部署运维专家 / 维护成本专家
**决策结果**: 方案A（放在 bot_civ repo 子目录）

---

## 议题背景

为 OpenClaw 编写了一个 botciv channel plugin（TypeScript），让 OpenClaw 作为 bot_civ 的原生 channel 接入。目前代码在远程服务器的 `/root/openclaw-botciv-plugin/` 目录，通过 `openclaw plugins link` 注册。

**Plugin 结构**：
- 6个文件，约 300 行 TypeScript
- 文件：`index.ts`, `package.json`, `src/channel.ts`, `src/monitor.ts`, `src/send.ts`, `src/outbound.ts`, `src/connection.ts`, `src/runtime.ts`

**bot_civ 项目结构**：
```
bot_civ/
├── server/          # Python FastAPI 后端
├── web/             # React 前端
├── docs/            # 文档
└── oc_bot.py        # 旧的 bot 脚本（已废弃）
```

**需要决策**：plugin 代码应该放在哪里？如何安装？

---

## 候选方案

### 方案 A：放在 bot_civ repo 的子目录
```
bot_civ/
├── server/
├── web/
├── openclaw-plugin/    # 新增
│   ├── index.ts
│   ├── package.json
│   └── src/
└── ...
```
- 安装：`openclaw plugins link /path/to/bot_civ/openclaw-plugin`

### 方案 B：独立 repo
```
openclaw-botciv-plugin/
├── index.ts
├── package.json
└── src/
```
- 安装：`openclaw plugins link /path/to/openclaw-botciv-plugin`

### 方案 C：发布为 npm 包
- 安装：`openclaw plugins install openclaw-botciv-plugin`

---

## 第一轮：多角度初步方案

### 🏗️ 架构设计专家

**推荐方案：A**

**核心优势**：
1. **耦合度匹配现实**：plugin 与 bot_civ 的 WebSocket 协议强耦合，协议变更必须同步修改。放在同一 repo 能保证原子性提交（一个 commit 同时改协议和 plugin）
2. **职责边界清晰**：plugin 本质是 bot_civ 的"客户端适配器"，不是独立产品。就像 React 项目里的 `adapters/` 目录，技术栈不同不影响逻辑归属
3. **扩展性不受影响**：未来其他人用时，clone bot_civ repo 即可，plugin 作为"官方客户端实现"存在。如果真有第三方需求，再抽离也不迟

**承认的不足**：
- Python 项目混入 TypeScript 子项目，CI/CD 需要配置两套工具链（pytest + npm test）
- 目录结构看起来"不纯粹"，但这是工程实用主义 vs 理想主义的权衡

---

### 🚀 部署运维专家

**推荐方案：A**

**核心优势**：
1. **部署步骤最少**：
   ```bash
   git clone bot_civ
   cd bot_civ/openclaw-plugin && npm install && npm run build
   openclaw plugins link $(pwd)
   ```
   只需一次 clone，不用管理两个 repo 的版本对应关系

2. **故障恢复简单**：plugin 挂了直接 `git pull` + `npm run build`，不用担心"plugin 版本 1.2 只兼容 bot_civ 0.8"的版本地狱
3. **自动化部署友好**：一个 Dockerfile 搞定，不用写复杂的 git submodule 或多 repo 编排脚本

**承认的不足**：
- 需要在 bot_civ 的 CI 里加 Node.js 环境（但现代 CI 都支持多语言，成本可控）
- 如果只想更新 plugin，也得 pull 整个 repo（但 300 行代码 + Python 后端总共也就几 MB）

---

### 🔧 维护成本专家

**推荐方案：A**

**核心优势**：
1. **零版本同步成本**：协议改了，同一个 PR 里改 plugin，测试通过即可合并。不会出现"server 改了协议，忘记通知 plugin repo"的人为失误
2. **开发体验最佳**：
   - 改协议时直接在同一编辑器窗口改 `server/` 和 `openclaw-plugin/`
   - 本地测试不用切目录、切 git branch
   - Code review 时能同时看到协议和 plugin 的改动
3. **文档维护简单**：`docs/api-contract.md` 和 plugin 实现在同一 repo，文档过期风险低

**承认的不足**：
- 如果未来 plugin 要支持多个 bot_civ 版本（如 v1.x 和 v2.x），单 repo 会有分支管理复杂度。但目前是单人项目，不存在这个问题

---

## 第二轮：协作融合

三方达成共识：**方案 A 是当前最优解**，理由高度一致：

1. **强耦合现实**：plugin 依赖 bot_civ 的 WebSocket 协议，这是无法解耦的硬依赖
2. **单人项目特性**：没有"多团队协作"的复杂性，不需要用独立 repo 来隔离开发节奏
3. **工程实用主义**：技术栈混合不是问题，现代项目（如 Next.js）常见 monorepo 包含多语言子项目

**对方案 B 的补充建议**：
- 如果未来有以下情况，再考虑拆分：
  - plugin 要支持多个 bot_civ 版本
  - 有第三方开发者想贡献 plugin（独立 repo 降低贡献门槛）
  - plugin 代码量超过 2000 行（当前 300 行，远未到阈值）

**对方案 C 的补充建议**：
- npm 发布适合"稳定 API + 多用户"场景，当前不符合
- 如果未来 bot_civ 成为开源项目，plugin 可以发布为 `@botciv/openclaw-plugin`

---

## 最终决策

### 推荐方案：A（放在 bot_civ repo 子目录）

**目录结构**：
```
bot_civ/
├── server/              # Python FastAPI
├── web/                 # React 前端
├── openclaw-plugin/     # TypeScript plugin
│   ├── package.json
│   ├── tsconfig.json
│   ├── index.ts
│   └── src/
│       ├── channel.ts
│       ├── monitor.ts
│       ├── send.ts
│       ├── outbound.ts
│       ├── connection.ts
│       └── runtime.ts
├── docs/
└── README.md
```

**安装流程**：
```bash
# 1. Clone repo
git clone https://github.com/zuiho-kai/bot_civ
cd bot_civ

# 2. 安装 plugin 依赖
cd openclaw-plugin
npm install
npm run build

# 3. 注册到 OpenClaw
openclaw plugins link $(pwd)

# 4. 验证
openclaw plugins list  # 应该看到 botciv-channel
```

---

## 对比表

| 维度 | 方案A（子目录） | 方案B（独立repo） | 方案C（npm包） |
|------|----------------|------------------|---------------|
| 维护成本 | ⭐⭐⭐⭐⭐ 零版本同步成本 | ⭐⭐ 需手动同步版本 | ⭐ 发布流程繁琐 |
| 部署便利性 | ⭐⭐⭐⭐⭐ 一次clone | ⭐⭐⭐ 需clone两个repo | ⭐⭐⭐⭐ npm install即可 |
| 代码耦合度 | ⭐⭐⭐ 符合强耦合现实 | ⭐⭐⭐⭐ 职责隔离清晰 | ⭐⭐⭐⭐ 标准化分发 |
| 扩展性 | ⭐⭐⭐⭐ 未来可拆分 | ⭐⭐⭐⭐⭐ 天然独立 | ⭐⭐⭐⭐⭐ 标准生态 |
| 当前适用性 | ⭐⭐⭐⭐⭐ 最适合单人项目 | ⭐⭐⭐ 过度设计 | ⭐ 没必要 |

---

## 实施建议

### 立即执行
1. 将远程服务器的 `/root/openclaw-botciv-plugin/` 移动到 `bot_civ/openclaw-plugin/`
2. 提交到 GitHub
3. 更新 `openclaw plugins link` 路径

### 文档补充
1. 在 `openclaw-plugin/README.md` 写安装和开发指南
2. 在 `docs/api-contract.md` 注明"plugin 实现在 `openclaw-plugin/src/`"
3. 在 `bot_civ/README.md` 添加 OpenClaw Plugin 章节

### CI/CD 配置建议（GitHub Actions）
```yaml
name: CI
on: [push, pull_request]
jobs:
  test-server:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: cd server && pip install -r requirements.txt && pytest

  test-plugin:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - run: cd openclaw-plugin && npm install && npm test && npm run build
```

### 未来迁移触发条件
满足任一即考虑拆分为独立 repo：
- plugin 代码量 > 2000 行
- 有 ≥2 个外部贡献者
- 需要支持多个 bot_civ 大版本

---

## 决策理由总结

1. **强耦合现实**：plugin 与 bot_civ WebSocket 协议强耦合，无法解耦
2. **零版本同步成本**：协议和 plugin 在同一 PR 修改，避免版本不匹配
3. **部署最简单**：一次 clone，一次 link，不用管理多 repo 版本对应
4. **开发体验最佳**：同一编辑器窗口改协议和 plugin，本地测试无需切目录
5. **单人项目特性**：没有多团队协作复杂性，不需要独立 repo 隔离
6. **工程实用主义**：技术栈混合不是问题，现代 monorepo 常见做法
7. **未来可拆分**：如果真有第三方需求或代码量暴增，再拆分也不迟
