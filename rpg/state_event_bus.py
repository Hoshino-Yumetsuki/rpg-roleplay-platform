"""
state_event_bus.py — task 69: 进程内 state-event 广播总线。

Dispatcher 在工具执行成功后调 emit(),订阅者(SSE endpoint per user)
就能把事件 push 给前端,前端转 CustomEvent("rpg-{topic}-updated") 触发
现有页面 reload — 无需手动刷新。

设计要点:
  · 进程内,不跨进程 (用 redis/postgres LISTEN 是后续优化)。
  · 按 user_id 分桶,跨用户互不可见 (安全)。
  · 订阅者拿 asyncio.Queue,非阻塞 push。
  · 超过 ttl 没人消费就丢 (避免泄漏)。
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StateEvent:
    user_id: int
    topic: str  # 例: "saves", "cards", "personas", "permissions", "scripts"
    op: str  # 例: "created", "deleted", "updated", "activated", "renamed"
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_sse_data(self) -> str:
        return json.dumps(
            {
                "topic": self.topic,
                "op": self.op,
                "payload": self.payload,
                "ts": self.ts,
            },
            ensure_ascii=False,
        )


# user_id → set of subscriber queues
_SUBSCRIBERS: dict[int, set[asyncio.Queue[StateEvent]]] = defaultdict(set)
_QUEUE_MAX = 64
# 安全: 单用户最多并发 SSE 订阅数。防止单用户开无限 SSE 连接吃光 fd/内存（DoS）。
MAX_SUBSCRIBERS_PER_USER = 10

# 线程安全: emit() 由 GM 工具循环在 *worker 线程* 调用(dispatcher 跑在 to_thread),
# 而 subscribe/unsubscribe/queue.get 在 *event-loop 线程*。两类线程并发读写
# _SUBSCRIBERS(set 迭代 vs discard/pop)→ RuntimeError: set changed size;
# 且 asyncio.Queue 非线程安全,跨线程 put_nowait 会损坏其 future 唤醒逻辑、丢事件。
# 用 _LOCK 串行化桶读写 + 把实际 put 经 call_soon_threadsafe 投递回 loop 线程。
_LOCK = threading.Lock()
_LOOP: asyncio.AbstractEventLoop | None = None


class TooManySubscribers(Exception):
    """订阅者超过 per-user 上限。"""


def subscribe(user_id: int) -> asyncio.Queue[StateEvent]:
    """SSE endpoint 调,拿一个新队列。endpoint 退出时务必 unsubscribe。

    超过 MAX_SUBSCRIBERS_PER_USER 上限时抛 TooManySubscribers, 路由层应
    返回 429 而不是继续累积。
    """
    global _LOOP
    try:
        # subscribe 总在 event-loop 线程的 SSE handler 里调 → 捕获该 loop 供 emit 跨线程投递
        _LOOP = asyncio.get_running_loop()
    except RuntimeError:
        pass
    with _LOCK:
        bucket = _SUBSCRIBERS[user_id]
        if len(bucket) >= MAX_SUBSCRIBERS_PER_USER:
            raise TooManySubscribers(
                f"user {user_id} 已达 SSE 订阅上限 ({MAX_SUBSCRIBERS_PER_USER}), "
                "请关掉旧标签页再重试"
            )
        q: asyncio.Queue[StateEvent] = asyncio.Queue(maxsize=_QUEUE_MAX)
        bucket.add(q)
    return q


def unsubscribe(user_id: int, q: asyncio.Queue[StateEvent]) -> None:
    with _LOCK:
        bucket = _SUBSCRIBERS.get(user_id)
        if bucket is None:
            return
        bucket.discard(q)
        if not bucket:
            _SUBSCRIBERS.pop(user_id, None)


def _deliver(q: asyncio.Queue[StateEvent], event: StateEvent) -> None:
    """在 event-loop 线程上执行的实际投递:满则丢最旧(背压)。"""
    try:
        q.put_nowait(event)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
            q.put_nowait(event)
        except Exception:
            pass


def emit(user_id: int, topic: str, op: str, payload: dict[str, Any] | None = None) -> None:
    """非阻塞 push 给该 user 的所有订阅者(可从任意线程调用)。
    队列满就丢最旧那条(背压),保证不阻塞 dispatcher 主路径。
    """
    event = StateEvent(user_id=user_id, topic=topic, op=op, payload=payload or {})
    with _LOCK:
        queues = list(_SUBSCRIBERS.get(user_id, ()))  # 锁内取快照,避免迭代时被改
    loop = _LOOP
    for q in queues:
        if loop is not None and loop.is_running():
            # 跨线程安全:把 put 调度回 loop 线程执行
            try:
                loop.call_soon_threadsafe(_deliver, q, event)
            except RuntimeError:
                # loop 正在关闭(进程收尾):丢弃该事件即可,不让异常冒泡进 dispatcher
                pass
        else:
            _deliver(q, event)


def subscriber_count(user_id: int) -> int:
    with _LOCK:
        return len(_SUBSCRIBERS.get(user_id, set()))


def reset_for_tests() -> None:
    global _LOOP
    with _LOCK:
        _SUBSCRIBERS.clear()
    _LOOP = None


__all__ = [
    "StateEvent",
    "subscribe",
    "unsubscribe",
    "emit",
    "subscriber_count",
    "reset_for_tests",
    "TooManySubscribers",
    "MAX_SUBSCRIBERS_PER_USER",
]
