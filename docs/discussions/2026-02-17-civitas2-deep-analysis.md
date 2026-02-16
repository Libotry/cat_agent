# CIVITAS2 深度分析 — M3 城市模拟参考

> 数据来源：DeepWiki 自动生成文档 (https://deepwiki.com/fengwewn/CIVITAS2)
> 分析目的：为 M3 城市模拟设计提供参考，提取可复用机制，明确差异化方向

---

## 一、CIVITAS2 系统全景

CIVITAS2 是一个 Django 实现的古典社会模拟系统，核心是"活动→资源→技能→属性"的循环。

### 核心循环

```
工作/副业 → 获得物资 + 技能提升
    ↓              ↓
消耗属性      物资 → 食谱 → 烹饪 → 恢复属性
    ↓
属性不足 → 无法继续工作 → 需要休息/进食
```

### 八大子系统

| 子系统 | 功能 | M3 参考价值 |
|--------|------|-------------|
| 用户系统 | 注册/登录/Session | 我们已有 Agent CRUD，不需要 |
| 四维属性 | 体力/快乐/健康/饥饿 | ⭐ 高参考 — 可简化为 M4 |
| 技能系统 | 大技能(7)+小技能(24)，突破机制 | M3 不做，M4 考虑 |
| 工作系统 | 主业+副业，产出物资 | ⭐ 高参考 — M3 核心 |
| 物资系统 | 资源获取/存储/品质等级 | ⭐ 中参考 — M3 简化版 |
| 饮食系统 | 食材+食谱+烹饪，恢复属性 | M3 不做 |
| 社交系统 | 演讲/博客/反应(欢呼/关注/倒彩) | 我们已有聊天群，不需要 |
| 天气系统 | 季节/温度/降水，影响工作效率 | M3 不做 |

---

## 二、关键机制深度拆解

### 2.1 四维属性系统

CIVITAS2 的角色有 4 个核心属性，初始值均为 100：

| 属性 | 作用 | 消耗来源 | 恢复方式 |
|------|------|----------|----------|
| 体力(energy) | 工作/社交的前提 | 工作(-15)、演讲(-15) | 每日恢复+30，住房加成 |
| 快乐(happiness) | 影响技能成长率 ±20% | 工作(-3) | 每日+3，食物 |
| 健康(health) | 影响体力恢复和工作产能 | 工作(-3)、饥饿过低 | 每日+3，食物 |
| 饥饿(hunger) | 过低会损害健康 | 自然衰减(-2 - 0.08×当前值) | 进食 |

关键公式：
- 快乐对技能的影响：`skill_increase *= (1 + (happiness - 60) / 200)`
- 住房加成：无房(+0) → 公寓L1(体力+10) → 公寓L2(体力+20, 快乐+0.4, 健康+0.4) → 庄园L2(体力+20, 快乐+0.8, 健康+0.8)

**M3 决策**：不引入四维属性。M3 只做"打卡→发薪→消费"闭环，属性系统是 M4 的深度玩法。

### 2.2 技能系统（二级层次）

```
大技能(7个)
├── 耕作: 粮食种植、蔬果种植、经济作物、开垦
├── 采伐: 采集、伐木、开采、勘探
├── 建设: 建筑、修缮
├── 加工: 冶炼、金属锻造、纺织、食品加工、木石加工
├── 社交: 雄辩、交际、文书、管理
├── 舟车: 陆上运输、水上运输、捕捞
└── 畜牧: 狩猎、家禽养殖、家畜养殖
```

技能成长公式：
```python
# 大技能成长（递减收益）
change = e^(-skill_now / 4)
change *= (1 + (happiness - 60) / 200)  # 快乐加成
change *= type_buff * strategy_buff
change *= (1 + comprehension / 4)        # 悟性加成

# 小技能成长
change = 0.03 * (1 + skill_now / 12) * (1 - skill_mini_now / 2)
```

突破机制：技能值每超过 4 点有突破机会，基础概率 0.5，受悟性和当前等级影响。

**M3 决策**：不做技能树。M3 的岗位是固定工资，不需要技能影响产出。

### 2.3 工作系统

CIVITAS2 有两种工作：

**主业(Main Work)**：
- 选择工作站 + 工作类型
- 消耗属性，获得物资 + 技能经验
- 实现不完整（代码中标注 under development）

**副业(Sideline)**：
- 完整实现，是主要的资源获取方式
- 每个副业配置：关联技能、产出系数、产品概率
- 产能公式：`capacity = 8 + (skill/2)^0.85 * (1 + mini_skill/2)`
- 每日活动次数有限，每次消耗递增

**教育(Education)**：
- 特殊副业，提升悟性(comprehension)
- 悟性公式：`change = 0.1 + skill_now / 100`
- 悟性影响未来所有技能成长速度

**M3 参考**：
- 我们的"打卡"对应 CIVITAS2 的副业，但大幅简化
- 不需要产能公式、技能关联、递增消耗
- M3 只需：Agent 选岗位 → 每日打卡 → 固定工资

### 2.4 物资系统

- 物资有品质等级(Q1/Q2/Q3)
- 通过工作获得，存入个人仓库
- 用于饮食系统（食材→食谱→烹饪）
- 不同品质影响营养属性

**M3 参考**：
- 我们的"虚拟物品"对应 CIVITAS2 的物资，但更简单
- M3 只需：商店固定商品 → 信用点购买 → 拥有记录
- 不需要品质等级、合成系统

### 2.5 社交系统

- 演讲(Speech)：发布短消息，消耗 15 体力，提升社交技能
- 话题标签：`#topic#` 格式自动提取
- 反应系统：欢呼/关注/倒彩（24小时内可反应）
- 热门演讲：按反应总数排序

**M3 参考**：我们已有聊天群 + 悬赏系统，社交功能更强。不需要参考。

### 2.6 饮食系统

- 食材(diet_material) → 食材属性(品质×营养×风味) → 食谱(recipe) → 烹饪 → 恢复属性
- 7 个营养/风味维度：健康度、饱食度、酸、咸、甜、苦、味道度
- 食谱是多对多关系（多种食材×数量）

**M3 决策**：不做。这是 CIVITAS2 最复杂的子系统之一，与我们的核心目标无关。

---

## 三、CIVITAS2 vs 我们的 M3 对比

| 维度 | CIVITAS2 | 我们的 M3 | 差异原因 |
|------|----------|-----------|----------|
| 货币 | 无货币系统（物资为主） | 信用点（已有） | 我们是 AI 经济驱动 |
| 工作 | 主业+副业+教育，技能关联产出 | 固定岗位+固定工资+打卡 | M3 验证闭环，不做复杂度 |
| 属性 | 四维(体力/快乐/健康/饥饿) | 不做 | M4 考虑 |
| 技能 | 7大+24小，突破+悟性 | 不做 | M4 考虑 |
| 物品 | 物资+品质+合成 | 虚拟商品（头像/称号） | M3 只验证消费端 |
| 社交 | 演讲+反应+话题 | 聊天群+悬赏（已有） | 我们的社交更强 |
| AI | 无 AI | LLM 驱动 Agent | 核心差异化 |
| 地图 | 无 | 无（M3），2D（M4+） | 一致 |

---

## 四、从 CIVITAS2 提取的 M3 设计启发

### 4.1 可直接参考的设计

1. **每日活动次数限制**：CIVITAS2 限制每日副业次数，消耗递增。M3 可简化为"每日打卡 1 次"。

2. **工作站概念**：CIVITAS2 有 work_station_id。M3 的岗位(job)类似，但不需要物理位置。

3. **工作记录表**：CIVITAS2 的 `work_record(uid, work_id, work_station_id, work_date)` 结构清晰。M3 的 `work_logs` 可参考。

4. **住房影响恢复**：CIVITAS2 住房等级影响属性恢复。M3 可以把"住房"作为虚拟商品，M4 再加属性加成。

### 4.2 明确不做的设计

1. **四维属性**：复杂度高，M3 不需要。
2. **技能树+突破+悟性**：CIVITAS2 最深的系统，M4 再考虑。
3. **饮食系统**：食材+食谱+烹饪，与我们的方向无关。
4. **天气系统**：环境影响工作效率，M3 不需要。
5. **品质等级**：物资 Q1/Q2/Q3，M3 商品不需要品质。

### 4.3 M4 可参考的设计

1. **技能影响产出**：`capacity = 8 + (skill/2)^0.85 * (1 + mini_skill/2)`
2. **快乐影响效率**：`modifier = 1 + (happiness - 60) / 200`
3. **住房等级加成**：不同住房提供不同恢复速率
4. **教育系统**：花时间提升悟性，长期收益
5. **递减收益**：`e^(-skill/4)` 防止技能无限增长

---

## 五、M3 Phase 1 数据模型确认

基于 CIVITAS2 分析和之前的五方讨论共识，M3 Phase 1 数据模型：

### jobs 表（岗位定义）
```sql
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,          -- 岗位名称
    description TEXT,            -- 岗位描述
    daily_salary INTEGER NOT NULL, -- 日薪（信用点）
    max_workers INTEGER DEFAULT 0, -- 最大工人数（0=无限）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### work_logs 表（打卡记录）
```sql
CREATE TABLE work_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents(id),
    job_id TEXT NOT NULL REFERENCES jobs(id),
    work_date DATE NOT NULL,     -- 打卡日期
    salary_paid INTEGER NOT NULL, -- 实际发放工资
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(agent_id, work_date)  -- 每人每天只能打卡一次
);
```

### virtual_items 表（虚拟商品）
```sql
CREATE TABLE virtual_items (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    item_type TEXT NOT NULL,      -- 'avatar_frame' | 'title' | 'decoration'
    price INTEGER NOT NULL,       -- 价格（信用点）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### agent_items 表（Agent 拥有的物品）
```sql
CREATE TABLE agent_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents(id),
    item_id TEXT NOT NULL REFERENCES virtual_items(id),
    purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(agent_id, item_id)    -- 每人每件商品只能买一次
);
```

---

## 六、结论

CIVITAS2 是一个偏重"生存模拟"的系统（工作→吃饭→维持属性→继续工作），我们的项目是"AI 社交经济"（聊天→工作→赚钱→消费→社交）。核心差异在于：

1. CIVITAS2 没有 AI，我们的 Agent 是 LLM 驱动的
2. CIVITAS2 没有货币，用物资循环；我们用信用点驱动经济
3. CIVITAS2 的深度在技能树和饮食系统；我们的深度在社交和记忆

M3 从 CIVITAS2 提取的核心参考：工作记录表结构、每日打卡限制、岗位概念。其余复杂机制（四维属性、技能树、饮食、天气）留给 M4+ 按需引入。
