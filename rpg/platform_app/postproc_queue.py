"""postproc_queue.py — W1 容量优化: Phase 4 后处理任务入队。

GM 流完后调 enqueue_postproc(),把 extractor / black_swan / phase_digest /
acceptance_verifier 写入 chat_postproc_tasks 并 NOTIFY chat_postproc_new 唤醒
独立 worker。主 worker 不再等待这些 LLM 调用,立刻释放 async slot。

并发回合容量: 25 → ~55 (回合时延 35s → 15s)。
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# enqueue 时可选任务种类
TASK_KINDS = ("extractor", "phase_digest", "acceptance_verifier", "black_swan", "image_gen")

_INSERT_SQL = """
INSERT INTO chat_postproc_tasks
    (user_id, save_id, commit_id, task_kind, payload, status, scheduled_at)
VALUES
    (%(user_id)s, %(save_id)s, %(commit_id)s, %(task_kind)s,
     %(payload)s::jsonb, 'pending', now())
"""


def enqueue_postproc(
    db: Any,
    *,
    user_id: int,
    save_id: str | int,
    commit_id: int | None,
    player_input: str,
    gm_output: str,
    api_user: dict[str, Any] | None,
    is_bs_enabled: bool,
    script_id: int | None = None,
    api_id_override: str | None = None,
    model_override: str | None = None,
    curator_plan: dict[str, Any] | None = None,
    state_data: dict[str, Any] | None = None,
) -> int:
    """把 Phase 4 后处理任务写入 chat_postproc_tasks,返回入队任务数。

    每个 task_kind 一行。payload 里带齐 worker 需要的参数。
    最后 NOTIFY chat_postproc_new 唤醒 worker(worker 也有 30s 兜底 poll)。
    """
    _save_id = str(save_id)
    _base_payload: dict[str, Any] = {
        "player_input": player_input,
        "gm_output": gm_output,
        "user_id": user_id,
        "save_id": _save_id,
        "script_id": script_id,
        "api_id_override": api_id_override,
        "model_override": model_override,
        "curator_plan": curator_plan or {},
        "state_snapshot_keys": list((state_data or {}).keys()),
    }

    # 只入队"在独立 worker 进程里真能工作"的后处理。
    # extractor / phase_digest 需要 FastAPI 进程内的实时 GameState(extractor 要 apply
    # ops 回 state、phase_digest 要按实时 phase 摘要),而 worker 是独立进程够不到内存态,
    # payload 也只带了 state_snapshot_keys(非完整 state)→ 二者在 worker 内是 no-op:
    # extractor 每轮白烧一次 LLM 调用再丢弃结果(record_usage 照样计费),phase_digest 调
    # 一个不存在的函数。故不下发,避免无效成本与僵尸任务行。这两项的状态依赖后处理仍由
    # GM 阶段内联路径(apply_structured_updates)+ sync 模式 _run_post_gm_parallel 承担。
    # acceptance_verifier(读 curator_plan+GM 文本,写 audit_log)、black_swan(enable_llm
    # =False 的确定性检查)不依赖实时内存态,worker 内可正确执行 → 保留。
    tasks = [
        ("acceptance_verifier", {**_base_payload, "curator_plan": curator_plan or {}}),
    ]
    if is_bs_enabled:
        tasks.append(("black_swan", {**_base_payload}))

    for task_kind, payload in tasks:
        db.execute(_INSERT_SQL, {
            "user_id": user_id,
            "save_id": _save_id,
            "commit_id": commit_id,
            "task_kind": task_kind,
            "payload": json.dumps(payload, ensure_ascii=False),
        })

    try:
        db.execute("SELECT pg_notify('chat_postproc_new', %s)", (str(user_id),))
    except Exception as _notify_exc:
        # NOTIFY 失败不影响入队;worker 30s 兜底 poll 会捞到任务
        log.warning("[postproc] NOTIFY failed (worker will poll): %s", _notify_exc)

    enqueued = len(tasks)
    log.info("[postproc] enqueueing %d postproc tasks for user=%s save=%s", enqueued, user_id, _save_id)
    return enqueued
