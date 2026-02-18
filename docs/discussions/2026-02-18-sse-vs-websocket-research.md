# SSE vs WebSocket 技术调研

**日期**: 2026-02-18
**类型**: 技术调研
**状态**: 已完成

## 调研目标

评估 Server-Sent Events (SSE) 作为 WebSocket 的轻量替代方案，重点关注：
1. 资源开销对比（内存、连接数、CPU）
2. 实时通知/事件推送场景的适用性
3. SSE 的局限性
4. 业界应用案例
5. 混合方案可行性

---

## 一、核心技术对比

### 1.1 协议特性

| 维度 | SSE | WebSocket |
|------|-----|-----------|
| **通信方向** | 单向（服务器→客户端） | 双向全双工 |
| **协议基础** | 标准 HTTP（chunked-encoding） | 独立协议（需协议升级） |
| **数据格式** | 仅 UTF-8 文本 | 文本 + 二进制 |
| **浏览器支持** | 98% | 97% |
| **自动重连** | 内置（Last-Event-ID 支持） | 需手动实现 |
| **实现复杂度** | 低（基于标准 HTTP） | 中等（需协议握手） |

### 1.2 资源开销对比

#### 内存占用
- **SSE 优势**：可丢弃已处理消息，不会累积缓存（"discard processed messages without accumulating all of them in memory"）
- **WebSocket**：需维护完整消息队列，内存占用随消息量增长

#### 连接数限制
- **HTTP/1.1 下的 SSE**：
  - 浏览器限制：每域名最多 6 个并发连接
  - 多标签页场景：50 个 widget × 10 个标签页 = 500 个连接（严重瓶颈）

- **HTTP/2 下的 SSE**：
  - **关键突破**：单连接多路复用，"only one connection per origin is required"
  - 所有 SSE 流共享一个 TCP 连接，消除连接数限制
  - 实测数据：HTTP/1.1 下 74% 连接仅传输单个事务，HTTP/2 下降至 25%

- **WebSocket**：
  - 不受 HTTP/2 多路复用影响（独立协议）
  - 每个 WebSocket = 1 个独立连接
  - 浏览器支持大量并发连接（无 6 连接限制）

#### CPU 开销
- **SSE**：基于 HTTP，协议处理简单，开销较低
- **WebSocket**：协议握手 + 帧解析，开销略高但可忽略
- **长轮询**：每次请求完整 HTTP 头（15 KB 头 + 5 KB 数据），开销最大

#### 移动设备影响
- **SSE**：支持 connectionless push，网络代理可管理连接，设备可休眠省电
- **WebSocket**：需全双工天线持续工作，电量消耗更高

---

## 二、扩展性与生产实践

### 2.1 单机性能

**LinkedIn 案例**：
- 通过硬件升级 + 内核参数调优
- 单台服务器支持 **数十万并发连接**

**Shopify 案例**：
- 使用 SSE 支持实时数据可视化
- 4 天内摄入 **3230 亿行数据**

**Split 案例**：
- 通过 Ably 平台使用 SSE
- 每月发送 **1 万亿事件**，全球平均延迟 < 300ms

### 2.2 水平扩展挑战

**SSE 扩展需求**：
- 多实例部署需消息代理（如 Redis）保证数据一致性
- 需负载均衡器（如 Nginx）分发连接
- 相比 WebSocket 扩展更简单（基于 HTTP，复用现有基础设施）

**WebSocket 扩展挑战**：
- 需维护连接状态映射
- 跨实例消息路由更复杂
- 但支持更复杂的双向交互场景

---

## 三、业界应用案例

### 3.1 Mastodon 实时推送架构

**技术栈**：
- 同时支持 SSE 和 WebSocket
- 后端使用 **Redis** 作为消息队列（`redis.publish()`）
- 流式服务可独立部署

**事件类型**（11 种）：
- `update`：新状态
- `delete`：删除状态
- `notification`：新通知
- `filters_changed`：过滤器变更
- `status.update`：状态编辑
- `conversation`：私信会话更新
- `announcement.*`：公告相关（3 种）
- `notifications_merged`：通知合并

**时间线分类**（12 种）：
- 公共时间线：`public`、`public:local`、`public:remote`（及 media 变体）
- 标签时间线：`hashtag`、`hashtag:local`
- 用户时间线：`user`、`user:notification`
- 列表：`list`
- 私信：`direct`

**认证机制**（v4.2.0+）：
1. **推荐**：`Authorization: Bearer <token>` HTTP 头
2. `Sec-Websocket-Protocol` 头（WebSocket）
3. `access_token` 查询参数（遗留，不推荐）

**WebSocket 多路复用**：
- 单连接支持动态订阅管理
- 通过 JSON 消息控制：`{"type": "subscribe", "stream": "hashtag:local", "tag": "foo"}`

### 3.2 其他业界案例

**Mercure.rocks 采用方**：
- **媒体娱乐**：M6（法国电视台）、Euro 2020、Wrestling
- **电商零售**：Printify、Lush
- **企业服务**：Rectangle Health、Sensiolabs
- **其他**：Climate Change Conference、Mail Tm

**架构特点**：
- "a thin layer on top of HTTP and SSE"（轻量封装层）
- "add streaming and asynchronous capabilities to REST and GraphQL APIs"
- 跨平台支持（Web、移动、IoT）

---

## 四、实现参考

### 4.1 FastAPI 实现（Python）

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

async def event_generator():
    # SSE 格式：data: <payload>\n\n
    for i in range(10):
        yield f"data: {json.dumps({'id': i, 'message': 'update'})}\n\n"

@app.get("/events")
async def sse_endpoint():
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

**性能特点**：
- 使用生成器模式，内存高效
- 避免加载完整响应到内存
- 支持异步生成器

### 4.2 SSE 标准格式

```
event: update
data: {"id": 123, "content": "..."}

event: notification
data: {"type": "mention", "user": "alice"}

:thump
```

- `event:` 指定事件类型
- `data:` 事件负载（可多行）
- `:` 开头为注释（用于心跳保活）

---

## 五、适用场景分析

### 5.1 推荐使用 SSE

✅ **理想场景**：
- 实时通知（新闻、社交动态、系统通知）
- 实时数据更新（股票行情、体育比分、位置追踪）
- 进度更新（文件上传、任务处理）
- IoT 设备状态推送
- 日志流式输出

✅ **技术优势**：
- 服务器主推数据，客户端偶尔发送更新
- 基于 HTTP，复用现有基础设施（负载均衡、CDN、防火墙友好）
- 自动重连 + 事件 ID 恢复
- HTTP/2 下无连接数限制

### 5.2 不推荐使用 SSE

❌ **不适合场景**：
- 聊天应用（需打字指示器、在线状态等双向特性）
- 多人游戏、协作编辑（需频繁双向交互）
- 需要二进制数据传输（视频流、文件传输）
- 需要客户端主动推送大量数据

❌ **技术限制**：
- 单向通信（客户端→服务器需额外 HTTP 请求）
- 仅支持 UTF-8 文本
- HTTP/1.1 下每域名 6 连接限制（HTTP/2 可解决）
- 不可扩展（需求变化可能需重构为 WebSocket）

### 5.3 混合方案

**推荐架构**：
- **聊天消息**：WebSocket（需双向实时交互）
- **系统通知**：SSE（单向推送，资源占用低）
- **在线状态**：WebSocket（需实时双向同步）
- **事件日志**：SSE（单向流式输出）

**Mastodon 实践**：
- 同时提供 SSE 和 WebSocket 端点
- 客户端根据场景选择协议
- 后端统一使用 Redis 消息队列

---

## 六、关键决策因素

### 6.1 选择 SSE 的条件

1. **通信模式**：服务器主推，客户端偶尔发送
2. **数据类型**：纯文本/JSON
3. **部署环境**：支持 HTTP/2（消除连接数限制）
4. **基础设施**：需复用现有 HTTP 栈（负载均衡、CDN）
5. **移动优先**：需省电（connectionless push）

### 6.2 选择 WebSocket 的条件

1. **通信模式**：频繁双向交互
2. **数据类型**：需二进制支持
3. **延迟要求**：极低延迟（< 50ms）
4. **扩展性**：需求可能演进为复杂双向场景
5. **连接数**：单域名需大量并发连接（HTTP/1.1 环境）

### 6.3 混合方案的条件

1. **场景分离**：聊天 vs 通知可明确区分
2. **资源优化**：通知量大但不需双向交互
3. **渐进迁移**：从 WebSocket 逐步拆分非关键路径到 SSE
4. **复杂度可控**：团队能维护两套协议栈

---

## 七、性能基准总结

| 维度 | SSE (HTTP/2) | WebSocket | 长轮询 |
|------|--------------|-----------|--------|
| **内存效率** | 高（可丢弃已处理消息） | 中（需维护消息队列） | 低（累积响应） |
| **连接数** | 1 个/域名（多路复用） | N 个（每 socket 1 个） | N 个（每请求 1 个） |
| **头开销** | 低（单次握手） | 低（单次握手） | 高（每次 15KB） |
| **延迟** | 低（< 300ms） | 极低（< 50ms） | 高（轮询间隔） |
| **电量消耗** | 低（可休眠） | 中（持续连接） | 高（频繁唤醒） |
| **扩展性** | 简单（HTTP 栈） | 中等（需状态管理） | 简单（无状态） |

---

## 八、推荐方案

### 8.1 纯 SSE 方案

**适用项目**：
- 实时通知系统
- 监控面板
- 日志查看器
- IoT 设备管理

**技术栈**：
- 后端：FastAPI `StreamingResponse` + Redis Pub/Sub
- 前端：原生 `EventSource` API
- 部署：Nginx HTTP/2 + 负载均衡

### 8.2 纯 WebSocket 方案

**适用项目**：
- 聊天应用
- 协作编辑
- 多人游戏
- 实时白板

**技术栈**：
- 后端：FastAPI WebSocket + Redis Pub/Sub
- 前端：原生 WebSocket API
- 部署：Nginx WebSocket 代理 + Sticky Session

### 8.3 混合方案（推荐 OpenClaw）

**架构设计**：
```
┌─────────────────────────────────────┐
│         前端客户端                   │
├─────────────────────────────────────┤
│  WebSocket          SSE             │
│  - 聊天消息         - 系统通知       │
│  - 在线状态         - Agent 状态更新 │
│  - 打字指示器       - 经济事件推送   │
└─────────────────────────────────────┘
           │                 │
           ▼                 ▼
┌─────────────────────────────────────┐
│         后端服务                     │
├─────────────────────────────────────┤
│  WebSocket Handler  SSE Handler     │
│         │                 │          │
│         └────── Redis ────┘          │
│              Pub/Sub                 │
└─────────────────────────────────────┘
```

**路由规则**：
- `/ws/chat` → WebSocket（聊天消息、在线状态）
- `/events/notifications` → SSE（系统通知）
- `/events/agent-status` → SSE（Agent 状态变化）
- `/events/economy` → SSE（经济事件）

**优势**：
- 聊天保持低延迟双向交互
- 通知/事件降低资源占用
- HTTP/2 下 SSE 无连接数限制
- 渐进迁移，风险可控

---

## 九、实施建议

### 9.1 短期（M2-M3）

1. **保持现有 WebSocket**：聊天功能已实现，不做改动
2. **新增 SSE 端点**：系统通知、Agent 状态推送使用 SSE
3. **监控对比**：收集两种协议的资源占用数据

### 9.2 中期（M4-M5）

1. **评估迁移**：根据监控数据决定是否扩大 SSE 使用范围
2. **优化部署**：确保 Nginx 启用 HTTP/2
3. **移动端优化**：利用 SSE 的 connectionless push 省电

### 9.3 长期（M6+）

1. **协议选择规范**：文档化 SSE vs WebSocket 的选择标准
2. **性能基准**：建立内部性能测试套件
3. **自动降级**：SSE 不可用时自动降级为长轮询

---

## 十、参考资料

1. **MDN - Server-Sent Events**: https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events
2. **Ably - SSE vs WebSocket**: https://ably.com/topic/server-sent-events
3. **Mastodon Streaming API**: https://docs.joinmastodon.org/methods/streaming/
4. **Mercure Protocol**: https://mercure.rocks/
5. **High Performance Browser Networking - HTTP/2**: https://hpbn.co/http2/

---

## 附录：快速决策树

```
需要双向频繁交互？
├─ 是 → WebSocket
└─ 否 → 需要二进制数据？
         ├─ 是 → WebSocket
         └─ 否 → 部署环境支持 HTTP/2？
                  ├─ 是 → SSE（推荐）
                  └─ 否 → 单域名需要 > 6 个并发连接？
                           ├─ 是 → WebSocket
                           └─ 否 → SSE
```
