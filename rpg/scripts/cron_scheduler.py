"""持续运行的 cron 调度器 — 用真正的 cron 表达式驱动 run_cron。

替代旧的 docker `while true; do run_cron all; sleep 86400; done` 裸循环
(那种写法只按"容器启动时刻 + 每 24h"跑,重启就漂移,且永远钉不到固定钟点)。

调度表达式由环境变量 RPG_CRON_SCHEDULE 控制(标准 5 段 cron,UTC 时区),
默认 "0 3 * * *" 即每天 03:00。可在 docker-compose 里手动覆盖,例如:
    RPG_CRON_SCHEDULE: "30 4 * * *"      # 每天 04:30
    RPG_CRON_SCHEDULE: "0 */6 * * *"     # 每 6 小时
要跑的子命令由 RPG_CRON_COMMAND 控制(默认 "all",见 scripts/run_cron.py)。

用法:
    python -m scripts.cron_scheduler
    RPG_CRON_SCHEDULE="*/30 * * * *" python -m scripts.cron_scheduler

注意:这是真正的 cron 语义——首次不会在容器启动时立即跑,而是等到表达式
匹配的下一个时刻。需要部署后立刻验证,可临时设 RPG_CRON_SCHEDULE 为近端时刻
或手动 `docker compose exec cron python -m scripts.run_cron all`。
"""
from __future__ import annotations

import logging
import os
import signal
import threading
from datetime import UTC, datetime

from croniter import croniter

from scripts.run_cron import main as run_cron_main

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger("cron_scheduler")

DEFAULT_SCHEDULE = "0 3 * * *"  # 每天 03:00 (UTC)

# 用 Event 而非裸 time.sleep:SIGTERM/SIGINT 可立即打断睡眠,让 `docker stop` 优雅快速退出。
_stop = threading.Event()


def _handle_signal(signum: int, _frame: object) -> None:
    logger.info("cron_scheduler: received signal %s, shutting down", signum)
    _stop.set()


def main() -> None:
    expr = (os.environ.get("RPG_CRON_SCHEDULE") or DEFAULT_SCHEDULE).strip()
    command = (os.environ.get("RPG_CRON_COMMAND") or "all").strip()

    # 坏表达式 fail-soft 回退到默认,否则容器会静默地永不执行任何任务。
    if not croniter.is_valid(expr):
        logger.error(
            "invalid RPG_CRON_SCHEDULE=%r; falling back to default %r",
            expr, DEFAULT_SCHEDULE,
        )
        expr = DEFAULT_SCHEDULE

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(
        "cron_scheduler started: schedule=%r command=%r (all times UTC)",
        expr, command,
    )

    while not _stop.is_set():
        now = datetime.now(UTC)
        nxt = croniter(expr, now).get_next(datetime)
        delay = max(0.0, (nxt - now).total_seconds())
        logger.info("next run at %s (in %.0fs)", nxt.isoformat(), delay)

        if _stop.wait(delay):  # 被信号打断 → True → 退出
            break

        logger.info("=== firing run_cron %s ===", command)
        try:
            # run_cron.main 用 (argv or sys.argv)[1:],会丢弃首元素 → 须补一个占位 argv[0]。
            run_cron_main(["cron_scheduler", command])
        except SystemExit as exc:
            # main() 仅在空/未知命令时 sys.exit;合法命令('all'等)不会触发。
            logger.error("cron_scheduler: run_cron exited (%s); stopping", exc)
            break
        except Exception:
            # 单次失败不能拖垮长驻调度器,记日志后继续等下一个周期。
            logger.exception("cron_scheduler: run_cron(%s) crashed; continuing", command)

    logger.info("cron_scheduler stopped.")


if __name__ == "__main__":
    main()
