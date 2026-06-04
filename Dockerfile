# ============================================================
# RPG Roleplay — Python (FastAPI/uvicorn) 生产镜像
# Stage 1 (frontend): node:lts-slim — vite build → frontend/dist
# Stage 2 (runtime):  ubuntu:24.04 + uv — uv sync(锁定) + uv run 启动
#
# 依赖单一来源:rpg/pyproject.toml + rpg/uv.lock(已无 requirements.txt)。
# Python 由 uv 管理的 standalone CPython 提供(版本见 rpg/.python-version=3.13)。
# ============================================================

FROM node:lts-slim AS frontend

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


# ─── Stage 2: Python 运行时 (ubuntu + uv) ────────────────────────────────────
FROM ubuntu:latest AS runtime

# 仅需 ca-certificates + curl(装 uv)。psycopg[binary]/cryptography/argon2-cffi
# 均有 manylinux wheel,无需编译链;若将来某依赖触发 source 构建,再加
# build-essential(+ 视情况 python3-dev / libpq-dev)。
RUN apt update
RUN apt upgrade -y \
    && apt autoremove -y \
    && apt clean
RUN apt install -y\
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 uv(官方脚本)。装到共享路径 /usr/local/bin 且不改 PATH(脚本默认装到
# ~/.local/bin,非 root 运行时取不到,故显式指定)。
ENV UV_INSTALL_DIR=/usr/local/bin
RUN curl -LsSf https://astral.sh/uv/install.sh | env INSTALLER_NO_MODIFY_PATH=1 sh

# uv 行为:
#   UV_PYTHON_INSTALL_DIR — 把 uv 托管的 CPython 装到共享目录(非 root 可读)
#   UV_PROJECT_ENVIRONMENT — venv 固定路径(构建/运行一致,供 `uv run --no-sync` 复用)
#   UV_COMPILE_BYTECODE   — 预编译 .pyc,加快冷启动
#   UV_LINK_MODE=copy     — 跨文件系统安全(避免 hardlink 告警)
#   UV_NO_CACHE=1         — 不读写缓存:镜像不留缓存层(更小),且非 root 无 home 时
#                           运行期 `uv run` 不会去碰 ~/.cache 而失败
ENV UV_PYTHON_INSTALL_DIR=/opt/uv/python \
    UV_PROJECT_ENVIRONMENT=/app/rpg/.venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

# app.py 的 import 用裸模块名(from app / from core.config),工作目录必须在 rpg/
WORKDIR /app/rpg

# 依赖层(命中 cache 的关键):只 copy 声明 + 锁文件 + python 版本,
# 装 python 并同步「生产依赖」(--no-dev 去掉 pytest/ruff/mypy;
# --no-install-project 不把本项目当包装,应用直接以源码运行)。
COPY rpg/pyproject.toml rpg/uv.lock rpg/.python-version ./
RUN uv python install \
    && uv sync --frozen --no-dev --no-install-project

# 后端代码(.venv 已被 .dockerignore 排除,不会覆盖上面 sync 出的环境)
COPY rpg/ /app/rpg/
# 前端源 + 从 stage 1 拷入构建产物 dist
COPY frontend/ /app/frontend/
COPY --from=frontend /build/frontend/dist /app/frontend/dist

# 非 root 运行:app 源码 + uv 托管 python + venv 全部交给 rpg 用户。
RUN groupadd -r rpg && useradd -r -g rpg -s /bin/false rpg \
    && chown -R rpg:rpg /app /opt/uv
USER rpg

EXPOSE 7860

STOPSIGNAL SIGTERM

# 单 worker(单进程 asyncio)。本应用持有进程内状态——SSE 事件总线
# (state_event_bus.py)与登录限流(auth.py)都是进程内 dict,多 worker 下
# 跨进程不共享:事件会丢、限流会被绕过。并发靠 asyncio 而非多进程
# (单 worker ~80 并发对话已足够)。需要横向扩展时用多副本 + 共享后端,不要加 worker。
# DB 连接:psycopg 池直连 postgres,大小取代码默认(RPG_DB_POOL_MAX,默认 10),
#   单进程下即真实 postgres 连接数,远低于 max_connections(默认 100)。
#
# 启动用 `uv run --no-sync`:复用构建期 sync 好的 venv,启动时不联网/不写盘
# (非 root 安全),只执行 venv 内的 python。
CMD ["uv", "run", "--no-sync", "python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--no-access-log"]
