"""
ST 公共工具：自动启动/停止服务器

用法：
    from server_utils import managed_server

    async def main():
        async with managed_server():
            # 服务器已就绪，跑测试
            ...
"""
import asyncio
import os
import signal
import subprocess
import sys
import time

import httpx

PORT = int(os.environ.get("E2E_PORT", "8001"))
BASE_URL = os.environ.get("E2E_BASE_URL", f"http://localhost:{PORT}")
_server_proc: subprocess.Popen | None = None


def _kill_existing(port: int) -> None:
    """kill 占用指定端口的进程（Windows + Unix 兼容）"""
    if sys.platform == "win32":
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                pid = parts[-1]
                try:
                    subprocess.run(["taskkill", "/F", "/PID", pid],
                                   capture_output=True)
                    print(f"  [server] killed PID {pid} on port {port}")
                except Exception:
                    pass
    else:
        subprocess.run(["fuser", "-k", f"{port}/tcp"],
                       capture_output=True)


def _start_server(port: int) -> subprocess.Popen:
    """启动 uvicorn，返回进程对象"""
    server_dir = os.path.dirname(os.path.abspath(__file__))
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--port", str(port), "--log-level", "warning"],
        cwd=server_dir,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


async def _wait_healthy(base_url: str, timeout: int = 30) -> bool:
    """轮询健康检查，最多等 timeout 秒"""
    deadline = time.time() + timeout
    async with httpx.AsyncClient() as client:
        while time.time() < deadline:
            try:
                r = await client.get(f"{base_url}/api/health", timeout=2)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False


class managed_server:
    """async context manager：进入时启动服务器，退出时关闭"""

    def __init__(self, port: int = PORT, base_url: str = BASE_URL):
        self.port = port
        self.base_url = base_url
        self._proc: subprocess.Popen | None = None

    async def __aenter__(self):
        global _server_proc
        print(f"[server] 启动服务器 (port={self.port})...")
        _kill_existing(self.port)
        await asyncio.sleep(0.5)
        self._proc = _start_server(self.port)
        _server_proc = self._proc

        ok = await _wait_healthy(self.base_url)
        if not ok:
            self._proc.kill()
            raise RuntimeError(f"服务器启动超时（port={self.port}）")
        print(f"[server] 就绪 {self.base_url}")
        return self

    async def __aexit__(self, *_):
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            print("[server] 已关闭")
