# 错题本 — 后端/API + 后端/环境

## API

### DEV-27 写 API 层只关注"能调通"，忽略系统边界防御 `🟡中频×2`

❌ Pydantic model 当透传容器不加边界约束（NaN/Infinity 穿透）；service 错误一刀切 400；不看 service 完整签名硬编码调用（漏 status_filter/offset）；`_map_error_status` 只写了"不能/已/不足"三个关键词，漏了"只能" → 返回 400 而非 409（二次复犯）
✅ 写 API 端点时：① 读 service 完整签名透传所有参数 ② 数值字段加 gt/ge/le + 非法值拦截 ③ 错误语义映射正确 HTTP 状态码 ④ **错误映射写完后 grep service 层所有 raise/return error 消息，逐条验证映射覆盖**

#### DEV-BUG-18 API 路由重复定义 + for...else 重复计数 `🟢`

❌ 新增路由没 grep 检查重复；`for...else` + 内部多分支各计 skipped，else 又多计一次
✅ 新增路由后 `grep -rn "路由路径" app/api/`；循环计数用 flag 变量替代 `for...else`

---

## 环境

#### DEV-BUG-1 Windows Python 指向 Store stub `🟢`

- **场景**: Windows 上直接运行 `python`
- **现象**: exit code 49，弹出 Microsoft Store
- **原因**: 系统 PATH 里 WindowsApps 的 stub 优先于实际安装的 Python
- **修复**: 用实际路径 `$LOCALAPPDATA/Programs/Python/Python312/python.exe` 创建 venv

#### DEV-BUG-3 Team 联调端口冲突 `🟢`

- **场景**: team-lead 和 backend-verifier 各自启动 uvicorn 绑同一端口
- **现象**: 第二个实例报 `[WinError 10048] 端口已被占用`
- **原因**: 多 agent 并行时没有约定谁负责启动服务
- **修复**: 有状态资源（端口、文件锁）由单一角色管理，启动前先检查 `curl localhost:8000/api/health`

#### DEV-BUG-4 Windows curl 中文 JSON body 400 `🟢`

- **场景**: Windows cmd/bash 下 curl 发送含中文的 JSON
- **现象**: 后端返回 400 body parsing error
- **原因**: Windows 终端编码问题，非服务端 bug
- **修复**: 用文件传 body（`curl -d @body.json`）或用 Python/httpx 测试
