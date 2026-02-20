# SR — M6 Phase 2：上网工具（web_search + web_fetch）

> 状态：已确认（DC-1~DC-4 全部拍板，2026-02-20）
> 前置：M6 Phase 1（策略自动机）✅ 已完成

---

## 1. 目标

让 Agent 在聊天回复和自主决策中能调用 `web_search` 和 `web_fetch` 两个工具，获取互联网实时信息。每次调用消耗 credits，有频率限制。

## 2. 范围

### 做

- `web_search` 工具：关键词搜索 → 返回摘要结果（标题+链接+摘要，最多 5 条）
- `web_fetch` 工具：抓取指定 URL → 返回纯文本摘要（最大 2000 字符）
- 三级 Provider fallback：① Jina API（默认）② Playwright（本地有则可选）③ httpx 直连（兜底）
- credits 扣费（web_search = 2 credits，web_fetch = 1 credit）
- 频率限制（每个 Agent 每小时最多 10 次）
- SSRF 防护（禁止访问内网地址 127.0.0.1/10.x/172.16-31.x/192.168.x）— 仅 httpx/Playwright provider 需要
- 内容安全截断（返回结果最大 2000 字符）
- 单元测试 + ST 脚本

### 不做

- 搜索结果缓存 — Phase 2 不做，后续按需加
- 前端 UI 展示搜索结果 — Agent 回复里自然包含即可
- autonomy_service SYSTEM_PROMPT 里的上网策略 — Phase 2 只注册工具，自主决策里暂不加上网动作

## 3. 阶段拆分

### T1：web_search 工具注册 + 后端实现

**改动文件：**
- `server/app/services/tool_registry.py` — 新增 `web_search` 工具注册 + handler
- `server/app/services/web_tools.py`（新建）— 搜索/抓取的实际实现，与 tool_registry 解耦
- `server/app/core/config.py` — 新增配置项

**验收：**
- [ ] `tool_registry.get_tools_for_llm()` 返回列表包含 `web_search`
- [ ] Agent 聊天中 LLM 可以调用 `web_search`，返回搜索结果
- [ ] credits 正确扣除
- [ ] 单元测试覆盖：正常搜索、credits 不足拒绝、频率超限拒绝

### T2：web_fetch 工具注册 + SSRF 防护

**改动文件：**
- `server/app/services/tool_registry.py` — 新增 `web_fetch` 工具注册 + handler
- `server/app/services/web_tools.py` — 新增 fetch 实现 + SSRF 检查函数
- `server/app/core/config.py` — 新增 `web_fetch_max_chars` 配置

**验收：**
- [ ] Agent 聊天中 LLM 可以调用 `web_fetch`，返回页面文本
- [ ] 内网地址（127.0.0.1、10.x、172.16-31.x、192.168.x）被拒绝
- [ ] 返回内容截断到 2000 字符
- [ ] credits 正确扣除
- [ ] 单元测试覆盖：正常抓取、SSRF 拦截、内容截断、credits 不足

### T3：ST 端到端验证

**改动文件：**
- `server/e2e_m6_p2.py`（新建）— ST 脚本
- `server/tests/test_web_tools.py`（新建）— 单元测试

**验收：**
- [ ] ST 场景 1：Agent 被 @"搜索今天的天气" → 调用 web_search → 回复包含搜索结果
- [ ] ST 场景 2：Agent 被要求抓取某 URL → 调用 web_fetch → 回复包含页面内容
- [ ] ST 场景 3：web_fetch 目标为 127.0.0.1 → 返回 SSRF 错误
- [ ] ST 场景 4：credits 为 0 时调用上网工具 → 拒绝执行

## 4. 阶段门禁

| 门禁 | 条件 |
|------|------|
| T1 → T2 | web_search 单元测试全绿 |
| T2 → T3 | web_fetch 单元测试全绿（含 SSRF） |
| T3 → 完成 | ST 全绿 + pytest 全绿 + Code Review P0/P1 归零 |

## 5. 设计决策（已确认）

### DC-1：搜索/抓取引擎 ✅

**方案：三级 Provider fallback**

| 优先级 | Provider | 适用场景 | 依赖 |
|--------|----------|----------|------|
| 1（默认） | Jina API（`s.jina.ai` 搜索 + `r.jina.ai` 抓取），无需 API key | 所有环境 | httpx |
| 2（可选） | Playwright 无头浏览器 | 本地开发、有 Chromium 的环境 | playwright |
| 3（兜底） | httpx 直连 | Jina 不可用时 | httpx |

- Jina API key（备用，暂不使用）：见 `.env` 文件
- 无 key 限制：Reader 20 RPM，Search 100 RPM（够用，Agent 每小时最多 10 次）
- 已验证：Reader + Search 均正常工作
- 服务器 2C2G 不装 Chromium，默认走 Jina

### DC-2：credits 消耗定价 ✅

| 操作 | 价格 | 理由 |
|------|------|------|
| web_search | 2 credits | Jina 免费，主要限制滥用 |
| web_fetch | 1 credit | 比搜索更轻量 |

### DC-3：频率限制 ✅

| 限制 | 值 | 理由 |
|------|-----|------|
| 每 Agent 每小时上网次数 | 10 次 | 防止滥用，够正常使用 |

### DC-4：网络代理 ✅

- Jina/httpx provider：走 `config.http_proxy`（默认 `http://127.0.0.1:7890`）
- Playwright provider：启动参数 `--proxy-server`
- 服务器环境可配置直连（`http_proxy = ""`）

---

## 6. AR 级别实施细节

> 以下为 Sonnet 终端可直接执行的详细指引。

### 6.1 新建文件：`server/app/services/web_tools.py`

**位置**：`E:\a3\server\app\services\web_tools.py`

**职责**：封装搜索和抓取的三级 Provider fallback，与 tool_registry 解耦。

**函数签名：**

```python
import httpx
import socket
import ipaddress
from urllib.parse import urlparse
from abc import ABC, abstractmethod
from app.core.config import settings

# --- SSRF 防护 ---

_BLOCKED_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
]

def is_ssrf(url: str) -> bool:
    """检查 URL 是否指向内网地址。返回 True = 危险，应拒绝。"""
    # 1. urlparse 提取 hostname
    # 2. socket.getaddrinfo 解析 DNS（防止 DNS rebinding）
    # 3. 检查 IP 是否在 _BLOCKED_NETS 中
    ...

# --- Provider 抽象 ---

class WebProvider(ABC):
    @abstractmethod
    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        """返回 [{"title": str, "url": str, "snippet": str}, ...]"""
        ...
    @abstractmethod
    async def fetch(self, url: str, max_chars: int = 2000) -> str:
        """返回纯文本（截断到 max_chars）"""
        ...

# --- Jina Provider（默认） ---

class JinaProvider(WebProvider):
    """通过 Jina API 搜索和抓取。s.jina.ai 搜索，r.jina.ai 抓取。"""

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        # GET https://s.jina.ai/{query}
        # Headers: Authorization: Bearer {settings.jina_api_key}, Accept: application/json
        # proxy=settings.http_proxy（如果非空）
        # 解析 JSON response → data 列表 → 取前 max_results 条
        # 每条提取 title, url, description(snippet)
        # 失败返回空列表
        ...

    async def fetch(self, url: str, max_chars: int = 2000) -> str:
        # 1. is_ssrf(url) → 拒绝（Jina 会访问目标 URL，但我们仍需检查）
        # 2. GET https://r.jina.ai/{url}
        # 3. Headers: Authorization: Bearer {settings.jina_api_key}, Accept: application/json
        # 4. proxy=settings.http_proxy（如果非空）
        # 5. 解析 JSON → data.content
        # 6. 截断到 max_chars
        ...

# --- Httpx Provider（兜底） ---

class HttpxProvider(WebProvider):
    """纯 HTTP 直连，DuckDuckGo HTML 解析搜索 + 直接抓取。"""

    async def search(self, query: str, max_results: int = 5) -> list[dict]:
        # GET https://html.duckduckgo.com/html/?q={query}
        # 解析 HTML 提取结果（简单正则或 BeautifulSoup）
        # 不稳定，仅作兜底
        ...

    async def fetch(self, url: str, max_chars: int = 2000) -> str:
        # 1. is_ssrf(url) → 拒绝
        # 2. httpx.get(url, proxy=settings.http_proxy, timeout=10)
        # 3. 简单 HTML 标签剥离（正则 re.sub(r'<[^>]+>', '', html)）
        # 4. 截断到 max_chars
        ...

# --- Provider 工厂 ---

def get_provider() -> WebProvider:
    """根据 settings.web_provider 返回对应 Provider 实例。"""
    # "jina"（默认）→ JinaProvider()
    # "httpx" → HttpxProvider()
    # "auto" → 有 jina_api_key 则 Jina，否则 httpx
    ...

# --- 对外接口（tool_registry 调用这两个） ---

async def web_search(query: str, max_results: int = 5) -> list[dict]:
    provider = get_provider()
    return await provider.search(query, max_results)

async def web_fetch(url: str, max_chars: int = 2000) -> str:
    provider = get_provider()
    return await provider.fetch(url, max_chars)
```

### 6.2 修改文件：`server/app/services/tool_registry.py`

**位置**：`E:\a3\server\app\services\tool_registry.py`（206 行）

**改动点**：在文件末尾（现有 5 个工具注册之后）追加 2 个工具注册。

**追加内容：**

```python
from app.services.web_tools import web_search, web_fetch, is_ssrf

# --- 频率限制内存计数器 ---
_web_usage: dict[int, list[float]] = {}  # agent_id → [timestamp, ...]

def _check_web_rate_limit(agent_id: int, max_per_hour: int = 10) -> bool:
    """检查 agent 是否超过每小时上网次数限制。返回 True = 允许。"""
    ...

# --- web_search handler ---

async def _handle_web_search(arguments: dict, context: dict) -> dict:
    """
    arguments: {"query": str}
    context: {"agent_id": int, "db": AsyncSession}
    流程：
    1. 检查频率限制
    2. 检查 credits >= 2（DC-2 定价）
    3. 扣除 2 credits
    4. 调用 web_search(query)
    5. 返回结果
    """
    ...

# --- web_fetch handler ---

async def _handle_web_fetch(arguments: dict, context: dict) -> dict:
    """
    arguments: {"url": str}
    context: {"agent_id": int, "db": AsyncSession}
    流程：
    1. is_ssrf(url) → 拒绝
    2. 检查频率限制
    3. 检查 credits >= 1
    4. 扣除 1 credit
    5. 调用 web_fetch(url)
    6. 返回结果
    """
    ...

# --- 注册 ---

tool_registry.register(ToolDefinition(
    name="web_search",
    description="搜索互联网获取实时信息。输入关键词，返回搜索结果摘要。每次消耗 2 credits。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"}
        },
        "required": ["query"]
    },
    handler=_handle_web_search,
))

tool_registry.register(ToolDefinition(
    name="web_fetch",
    description="抓取指定 URL 的网页内容，返回纯文本摘要（最多 2000 字符）。每次消耗 1 credit。禁止访问内网地址。",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "要抓取的网页 URL"}
        },
        "required": ["url"]
    },
    handler=_handle_web_fetch,
))
```

### 6.3 修改文件：`server/app/core/config.py`

**位置**：`E:\a3\server\app\core\config.py`（124 行）

**改动点**：在 Settings 类中新增配置项。

```python
# 上网工具配置
http_proxy: str = "http://127.0.0.1:7890"  # 服务器环境设为 "" 直连
# Jina API key 备用（暂不使用）: 见 .env 文件
jina_api_key: str = ""                     # 留空 = 无 key 模式（Reader 20RPM, Search 100RPM）
jina_search_base: str = "https://s.jina.ai"
jina_reader_base: str = "https://r.jina.ai"
web_provider: str = "auto"                 # "auto" / "jina" / "httpx"
web_search_cost: int = 2                   # credits per search
web_fetch_cost: int = 1                    # credits per fetch
web_fetch_max_chars: int = 2000            # 抓取内容最大字符数
web_rate_limit_per_hour: int = 10          # 每 Agent 每小时上网次数上限
```

### 6.4 新建文件：`server/tests/test_web_tools.py`

**位置**：`E:\a3\server\tests\test_web_tools.py`

**测试用例：**

```
test_is_ssrf_blocks_localhost        — 127.0.0.1 → True
test_is_ssrf_blocks_private_10       — 10.0.0.1 → True
test_is_ssrf_blocks_private_172      — 172.16.0.1 → True
test_is_ssrf_blocks_private_192      — 192.168.1.1 → True
test_is_ssrf_allows_public           — 8.8.8.8 → False
test_web_search_returns_results      — mock Jina API → 返回列表
test_web_search_empty_on_error       — mock Jina API 500 → 返回空列表
test_web_fetch_returns_text          — mock Jina API → 返回文本
test_web_fetch_truncates             — 超长内容 → 截断到 2000
test_web_fetch_rejects_ssrf          — 127.0.0.1 → 拒绝
test_handle_web_search_deducts_credits   — credits 从 100 变 98
test_handle_web_search_rejects_no_credits — credits=0 → 拒绝
test_handle_web_fetch_deducts_credits    — credits 从 100 变 99
test_rate_limit_blocks_after_max     — 第 11 次 → 拒绝
test_provider_factory_auto           — 有 jina key → JinaProvider
test_provider_factory_httpx          — 无 jina key → HttpxProvider
```

### 6.5 新建文件：`server/e2e_m6_p2.py`

**位置**：`E:\a3\server\e2e_m6_p2.py`

**ST 场景：**

```
ST-1: web_search 正常调用
  - POST /api/dev/trigger 发送 "@Agent1 搜索一下今天的新闻"
  - 等待 Agent 回复
  - 验证回复包含搜索结果关键词
  - 验证 credits 减少

ST-2: web_fetch 正常调用
  - POST /api/dev/trigger 发送 "@Agent1 帮我看看 https://example.com 的内容"
  - 等待 Agent 回复
  - 验证回复包含页面内容

ST-3: web_fetch SSRF 防护
  - 直接调用 web_fetch handler，url=http://127.0.0.1:8000
  - 验证返回 SSRF 错误

ST-4: credits 不足拒绝
  - 设置 Agent credits=0
  - 调用 web_search handler
  - 验证返回 credits 不足错误
```

### 6.6 不改动的文件（确认）

| 文件 | 原因 |
|------|------|
| `agent_runner.py` | 不改 — 已有 tool_call 循环，新工具自动被 LLM 调用 |
| `autonomy_service.py` | 不改 — Phase 2 不在自主决策里加上网动作 |
| `strategy_engine.py` | 不改 — 上网不是策略类型 |
| `前端所有文件` | 不改 — Agent 回复里自然包含搜索结果，无需 UI 变更 |

---

## 7. 文件路径速查

| 文件 | 路径 | 操作 |
|------|------|------|
| web_tools.py | `E:\a3\server\app\services\web_tools.py` | 新建 |
| tool_registry.py | `E:\a3\server\app\services\tool_registry.py` | 追加 ~60 行 |
| config.py | `E:\a3\server\app\core\config.py` | 追加 ~8 行 |
| test_web_tools.py | `E:\a3\server\tests\test_web_tools.py` | 新建 |
| e2e_m6_p2.py | `E:\a3\server\e2e_m6_p2.py` | 新建 |

**参考文件（只读，用于对齐格式）：**
| 文件 | 路径 | 参考什么 |
|------|------|----------|
| tool_registry.py | `E:\a3\server\app\services\tool_registry.py` | 工具注册格式、handler 签名 |
| agent_runner.py | `E:\a3\server\app\services\agent_runner.py` | tool_call 循环（行 113-146） |
| e2e_m6.py | `E:\a3\server\e2e_m6.py` | ST 脚本结构、断言方式 |
| test_m6_strategy.py | `E:\a3\server\tests\test_m6_strategy.py` | 单元测试 fixture、mock 模式 |
| conftest.py | `E:\a3\server\tests\conftest.py` | db fixture |
