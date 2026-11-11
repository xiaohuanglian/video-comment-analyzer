import asyncio
import logging
from typing import Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services import crawler_manager

router = APIRouter(tags=["websocket"])

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket connection manager"""

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)

    async def broadcast(self, message: dict):
        """Broadcast message to all connections"""
        if not self.active_connections:
            return

        disconnected = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up disconnected connections
        for conn in disconnected:
            self.disconnect(conn)


manager = ConnectionManager()


async def log_broadcaster():
    """Background task: read logs from queue and broadcast"""
    queue = crawler_manager.get_log_queue()
    while True:
        try:
            # Get log entry from queue
            entry = await queue.get()
            # Broadcast to all WebSocket connections
            await manager.broadcast(entry.model_dump())
        except asyncio.CancelledError:
            break
        except Exception:  # noqa: BLE001 - 广播失败不该让整个任务退出
            logger.exception("[WS] 日志广播异常")
            await asyncio.sleep(0.1)


# Global broadcast task
_broadcaster_task: Optional[asyncio.Task] = None


def start_broadcaster():
    """Start broadcast task"""
    global _broadcaster_task
    if _broadcaster_task is None or _broadcaster_task.done():
        _broadcaster_task = asyncio.create_task(log_broadcaster())


def _origin_allowed(origin: str) -> bool:
    """WebSocket 来源校验。

    2026-11-11 审计：`/api/ws/logs` 直接 accept 任何来源，浏览器里任意网页
    都能连上并读到采集日志（含视频标题、评论者昵称等）。虽然服务绑定在
    127.0.0.1，但本机浏览器访问的恶意页面同样在攻击面内。

    规则：无 Origin（非浏览器客户端，如 CLI/测试）放行；
    有 Origin 时只接受本机来源，与 CORS 白名单保持一致。
    """
    if not origin:
        return True
    allowed = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8766",
        "http://127.0.0.1:8766",
    }
    return origin.rstrip("/") in allowed


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket log stream"""
    origin = websocket.headers.get("origin", "")
    if not _origin_allowed(origin):
        logger.warning("[WS] 拒绝来源不明的连接：%s", origin)
        await websocket.close(code=1008)  # policy violation
        return

    try:
        start_broadcaster()
        await manager.connect(websocket)
        logger.debug("[WS] 已连接，当前连接数 %s", len(manager.active_connections))

        for log in crawler_manager.logs:
            try:
                await websocket.send_json(log.model_dump())
            except Exception:  # noqa: BLE001 - 单条推送失败就断开，不必刷屏
                logger.debug("[WS] 推送历史日志失败，断开")
                break

        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                if data == "ping":
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                try:
                    await websocket.send_text("ping")
                except Exception:  # noqa: BLE001
                    break
    except WebSocketDisconnect:
        logger.debug("[WS] 客户端断开")
    except Exception:  # noqa: BLE001
        logger.exception("[WS] 日志流异常")
    finally:
        manager.disconnect(websocket)


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    """WebSocket status stream"""
    origin = websocket.headers.get("origin", "")
    if not _origin_allowed(origin):
        logger.warning("[WS] 拒绝来源不明的状态连接：%s", origin)
        await websocket.close(code=1008)
        return

    await websocket.accept()
    try:
        while True:
            await websocket.send_json(crawler_manager.get_status())
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - 客户端断开是常态
        logger.debug("[WS] 状态流中止")
