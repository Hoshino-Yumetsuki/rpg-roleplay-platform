# ============================================================
# RPG Roleplay — Python (FastAPI/uvicorn) 生产镜像
# Stage 1 (frontend): node:lts-slim — vite build → frontend/dist
# Stage 2 (runtime):  python:3.14-slim — pip install + uvicorn
#
# 注意:main 分支已切回 Python 产品线(rust/ 归档在 archive/rust-migration)。
# 旧的 Rust 版 Dockerfile 保留在该归档分支。
# ============================================================

# ─── Stage 1: 构建前端 dist ──────────────────────────────────────────────────
# 前端是 Vite ESM,必须先 build 产出 frontend/dist(打包后的 /assets/*.js);
# 后端 app.py 同源挂载 frontend/dist。
FROM node:lts-slim AS frontend

WORKDIR /build/frontend
# 先复制 lockfile 利用 layer cache
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


# ─── Stage 2: Python 运行时 ──────────────────────────────────────────────────
FROM python:3.14-slim AS runtime

# 运行时库 + 编译依赖兜底(Python 3.14 较新,个别包可能无预编译 wheel)。
# libpq-dev/gcc 用于 pip 编译;运行时 psycopg-binary 自带 libpq。
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gcc libpq-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 非 root 运行
RUN groupadd -r rpg && useradd -r -g rpg -s /bin/false rpg

WORKDIR /app

# 先装依赖(利用 layer cache:requirements 不变则跳过)
COPY rpg/requirements.txt /app/rpg/requirements.txt
RUN pip install --no-cache-dir -r /app/rpg/requirements.txt

# 后端代码
COPY rpg/ /app/rpg/
# 前端源 + 从 stage 1 拷入构建产物 dist
COPY frontend/ /app/frontend/
COPY --from=frontend /build/frontend/dist /app/frontend/dist

RUN chown -R rpg:rpg /app
USER rpg

# app.py 的 import 用裸模块名(from app / from core.config),工作目录必须在 rpg/
WORKDIR /app/rpg

EXPOSE 7860

STOPSIGNAL SIGTERM

# 单 worker(单进程 asyncio)。本应用持有进程内状态——SSE 事件总线
# (state_event_bus.py)与登录限流(auth.py)都是进程内 dict,多 worker 下
# 跨进程不共享:事件会丢、限流会被绕过。并发靠 asyncio 而非多进程
# (单 worker ~80 并发对话已足够)。需要横向扩展时用多副本 + 共享后端,不要加 worker。
# DB 连接:psycopg 池直连 postgres,大小取代码默认(RPG_DB_POOL_MAX,默认 10),
#   单进程下即真实 postgres 连接数,远低于 max_connections(默认 100)。
CMD ["/bin/sh", "-c", "exec python -m uvicorn app:app --host 0.0.0.0 --port 7860 --no-access-log"]
