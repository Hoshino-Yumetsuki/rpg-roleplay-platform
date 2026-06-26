# 拆分方案:rpg/platform_app/api/admin.py(1464 行)

> 审计日期:2026-06-10 · 体检类型:函数抽象层 + 拆分可行性
> 结论:**needs-refactor(低优先级,工作量 S)** — 6 个内聚簇边界清晰、外部唯一消费者是 `router`、测试 patch 点 **0 个**,拆分风险接近零;但当前无行为耦合之痛,不紧急。

---

## 1. 现状结构图

文件 = 「/api/admin/* 全部路由」聚合体:**38 个 @router 端点 + 5 个模块内辅助函数**,自带章节注释(2.2~3.4),实际横跨 6 个互不调用的子领域:

```
admin.py (1464 行)
├─ 共享辅助(4 个,被各簇横向复用)
│   _require_admin @29          ← FastAPI Depends,除 1 个端点外全部使用
│   _get_app_config @40 / _set_app_config @48   ← 仅 config 簇使用
│   _write_audit @58            ← 用户管理/config/DMCA/CSAM/AUP 使用
│   常量:_REGISTRATION/_SECURITY/_MAINTENANCE_CFG_KEY
├─ 簇 A:用户管理(2.2,@87-268,~185 行)
│   admin_list_users / admin_update_user / admin_deactivate_user /
│   admin_reactivate_user / admin_force_logout_user
├─ 簇 B:运维观测(2.3-2.6,@276-521,~250 行)
│   admin_usage(83 行) / admin_audit_log / admin_health(74 行) / admin_logs
├─ 簇 C:平台配置(2.7-2.10,@528-782,~260 行)
│   _DEFAULT_REGISTRATION + registration get/set
│   invite-codes list/create/delete
│   _DEFAULT_SECURITY + security-config get/set
│   _DEFAULT_MAINTENANCE + maintenance get/set
│   admin_restart(SIGHUP 自重启)
├─ 簇 D:信任与安全 T&S(3.1-3.4,@790-1165,~380 行)
│   DMCA takedowns:list/create/action/counter
│   DMCA strikes:list/increment(调 platform_app.dmca.increment_strike)
│   CSAM reports:list/decision
│   AUP:suspend/unsuspend/terminate(调 queue_account_termination)
├─ 簇 E:注册白名单 + 共建者(@1172-1338,~170 行)
│   api_bulk_allowlist / api_list_allowlist / admin_co_builders /
│   api_internal_allowlist_bulk(68 行,唯一不走 _require_admin 的端点,
│                                X-Internal-Secret 跨服务认证)
└─ 簇 F:成就目录管理(@1344-1463,~120 行)
    import re as _re(文件中部!)+ _ACHV_SLUG / _ACHV_TIERS
    _achv_validate_payload + 4 个 CRUD 端点
```

### 依赖事实(全部 Grep 实查)

| 事实 | 结果 |
|---|---|
| 谁 import 本模块 | **仅 1 处**:`rpg/platform_app/api/__init__.py:18` `from .admin import router as _admin_router` |
| rpg/tests 中 mock.patch / monkeypatch 指向本模块 | **0 处**(`grep -rn "patch\|monkeypatch" rpg/tests/ | grep admin` 无 `platform_app.api.admin` 命中) |
| rpg/tests 中调用 `/api/admin/*` 端点 | **0 处**(`grep -rn "/api/admin/" rpg/tests/` 空;security 测试里的 `_admin_cookies` 只打 `/api/skills/*`) |
| 其他文件里的同名 `_require_admin`/`_write_audit` | feedback.py / policy.py / api/auth.py / platform_app/auth.py / run_cron.py 各自有**本地独立副本**,与本文件无 import 关系 |
| `admin.registration_config` 等 app_config key | `platform_app/auth.py:355,512` 用**字符串字面量直查 DB**,不 import 本模块常量 |
| `Path(__file__)` / 相对路径 | **0 处**(仅 `open(log_file)`,log_file 来自 env `LOG_FILE`,与模块位置无关) |
| 模块级副作用 | `router = APIRouter()` 单例 + 38 个装饰器注册;路由 path 全部唯一,include 顺序无冲突 |

## 2. 内聚簇分析与判定

- **每个端点函数本身抽象层干净**:handler → SQL → `json_response`,无层级混杂;唯一 ≥80 行函数 `admin_usage`(83 行)是 4 条独立聚合 SQL + 组装,**纯数据表型,不应拆阶段函数**(拆了只会把 4 条 SQL 藏进 4 个一次性调用的小函数,降低可读性)。`admin_health`(74 行)同理是探针清单型。
- **文件层面职责混杂是真实的**:T&S(DMCA/CSAM/AUP,法务敏感)、平台配置、运维观测、成就目录是四类演进节奏完全不同的代码,且**簇间零相互调用**(只共享 4 个小辅助)。admin 面板历史上持续增长(成就管理是后期 append),不拆会继续膨胀。
- **拆分成本异常低**:外部只消费 `router`、零 patch 点、零测试端点覆盖、零 `__file__` 陷阱 → 这是全仓库最安全的拆分候选。
- 判定 **needs-refactor / priority=low / effort=S**:值得拆,但没有任何现刻痛点逼迫,可排期在空窗期由 sonnet 子代理机械执行。

## 3. 目标布局(module → package,仿 `api/__init__.py` 既有聚合惯例)

```
rpg/platform_app/api/admin/
├─ __init__.py        (~45 行)  聚合 router + re-export 辅助符号(shim)
├─ _common.py         (~65 行)  共享辅助
├─ users.py           (~195 行) 簇 A
├─ observability.py   (~260 行) 簇 B
├─ platform_config.py (~270 行) 簇 C
├─ trust_safety.py    (~390 行) 簇 D
├─ allowlist.py       (~180 行) 簇 E
└─ achievements.py    (~130 行) 簇 F
```

- 每个子模块自带 `router = APIRouter()`,`__init__.py` 逐一 `include_router`。
- **`from .admin import router` 在 api/__init__.py 中一字不改**(包替换模块,导入路径不变 → 这就是 shim)。
- `_deps`/`_card_dto` 前缀下划线 = 包内辅助的既有惯例,`_common.py` 沿用。
- 子包内命名 `achievements.py` 与顶层 `platform_app/achievements/` 不冲突:函数内 `from platform_app.achievements import validate_rule` 是绝对导入,Python 3 无隐式相对导入。

### `admin/__init__.py` 内容(shim 全文骨架)

```python
"""platform_app.api.admin — /api/admin/* 路由(需 admin 角色),按子领域拆 sub-router。"""
# ruff: noqa: F401
from fastapi import APIRouter

router = APIRouter()

from .users import router as _users_router
from .observability import router as _obs_router
from .platform_config import router as _cfg_router
from .trust_safety import router as _ts_router
from .allowlist import router as _allow_router
from .achievements import router as _achv_router

router.include_router(_users_router)
router.include_router(_obs_router)
router.include_router(_cfg_router)
router.include_router(_ts_router)
router.include_router(_allow_router)
router.include_router(_achv_router)

# re-export:保持 platform_app.api.admin.<符号> 旧路径可用(防未来 patch/import 断裂)
from ._common import (
    _require_admin, _get_app_config, _set_app_config, _write_audit,
    _REGISTRATION_CFG_KEY, _SECURITY_CFG_KEY, _MAINTENANCE_CFG_KEY,
)
```

## 4. 可机械执行的搬运清单(符号名 → 目标文件;**逐字搬运,禁止改写任何函数体/SQL/注释**)

每个子模块头部统一新建样板(非搬运):`from __future__ import annotations`、所需 import(从原文件头 @1-22 按需复制)、`router = APIRouter()`、`log = logging.getLogger(__name__)`(observability/users 需要)。簇内符号**按原文件行号顺序**搬,章节横幅注释一并带走。

| # | 符号(@原起始行) | 目标文件 |
|---|---|---|
| 1 | `_require_admin` @29 | `_common.py` |
| 2 | `_REGISTRATION_CFG_KEY` `_SECURITY_CFG_KEY` `_MAINTENANCE_CFG_KEY` @35-37 | `_common.py` |
| 3 | `_get_app_config` @40 | `_common.py` |
| 4 | `_set_app_config` @48 | `_common.py` |
| 5 | `_write_audit` @58 | `_common.py` |
| 6 | `admin_list_users` @87 | `users.py` |
| 7 | `admin_update_user` @155 | `users.py` |
| 8 | `admin_deactivate_user` @205 | `users.py` |
| 9 | `admin_reactivate_user` @233 | `users.py` |
| 10 | `admin_force_logout_user` @252 | `users.py` |
| 11 | `admin_usage` @276 | `observability.py` |
| 12 | `admin_audit_log` @366 | `observability.py` |
| 13 | `admin_health` @410 | `observability.py` |
| 14 | `admin_logs` @491 | `observability.py` |
| 15 | `_DEFAULT_REGISTRATION` @528 | `platform_config.py` |
| 16 | `admin_get_registration` @536 / `admin_set_registration` @544 | `platform_config.py` |
| 17 | `admin_list_invite_codes` @563 / `admin_create_invite_codes` @607 / `admin_delete_invite_code` @658 | `platform_config.py` |
| 18 | `_DEFAULT_SECURITY` @682 / `admin_get_security_config` @696 / `admin_set_security_config` @704 | `platform_config.py` |
| 19 | `_DEFAULT_MAINTENANCE` @725 / `admin_get_maintenance` @733 / `admin_set_maintenance` @741 | `platform_config.py` |
| 20 | `admin_restart` @770 | `platform_config.py` |
| 21 | `admin_dmca_list` @791 / `admin_dmca_create` @815 / `admin_dmca_action` @853 / `admin_dmca_counter` @890 | `trust_safety.py` |
| 22 | `admin_dmca_strikes_list` @927 / `admin_dmca_strike_increment` @966 | `trust_safety.py` |
| 23 | `admin_csam_list` @1003 / `admin_csam_decision` @1029 | `trust_safety.py` |
| 24 | `admin_suspend_user` @1068 / `admin_unsuspend_user` @1120 / `admin_terminate_user` @1143 | `trust_safety.py` |
| 25 | `api_bulk_allowlist` @1173 / `api_list_allowlist` @1202 | `allowlist.py` |
| 26 | `admin_co_builders` @1244 | `allowlist.py` |
| 27 | `api_internal_allowlist_bulk` @1271(注意:**不依赖** `_require_admin`,函数内 `import redis_bus` 保持原样) | `allowlist.py` |
| 28 | `import re as _re` @1344 + `_ACHV_SLUG` @1346 + `_ACHV_TIERS` @1347 | `achievements.py`(可提到文件头,内容不改) |
| 29 | `_achv_validate_payload` @1350(函数内 `from platform_app.achievements import validate_rule` 保持原样) | `achievements.py` |
| 30 | `admin_achv_list` @1391 / `admin_achv_create` @1401 / `admin_achv_update` @1426 / `admin_achv_delete` @1453 | `achievements.py` |

各子模块需要的辅助统一 `from ._common import ...`;各簇所需外部 import:
- 全部:`from fastapi import APIRouter, Depends, HTTPException, Request`(按簇裁剪)、`from platform_app.db import connect`、`from platform_app.api._deps import _client_ip, json_response`(users/observability 还需无;`require_user` 只被 `_common._require_admin` 用)
- `_common.py`:`from psycopg.types.json import Jsonb`、`from platform_app.api._deps import require_user`
- `observability.py`:`os, sys, time, logging`
- `platform_config.py`:`os, signal, secrets, string`、`from datetime import datetime, timezone`
- `trust_safety.py`:`from platform_app.dmca import increment_strike, queue_account_termination`
- `allowlist.py`:`os, secrets`
- `achievements.py`:`from psycopg.types.json import Jsonb`

## 5. 五大陷阱对照 + 其他风险核查

| 陷阱 | 核查结果 | 对策 |
|---|---|---|
| ① 测试 patch 命名空间穿透 | **patch 点 = 0**(Grep 实查 rpg/tests 全量:无 `mock.patch`/`monkeypatch` 指向 `platform_app.api.admin`,无测试调 `/api/admin/*`) | 仍在 `__init__.py` re-export 全部 `_common` 符号,使 `platform_app.api.admin._write_audit` 等旧路径继续可 patch(对未来测试免疫) |
| ② Path(__file__) 错位 | **0 处**;唯一文件 IO 是 `open(log_file)`,路径来自 env `LOG_FILE`,与模块位置无关;`os.statvfs("/")` 绝对路径 | 无需处理 |
| ③ 执行代理顺手简化 | 风险点:`admin_usage` 4 条相似 SQL、invite-codes 的 insert 双分支、`api_internal_allowlist_bulk` 的 try/except 计数 | 方案明令:**逐字搬运,禁止合并 SQL/改写分支/「优化」异常处理**;搬运清单按符号逐条对账;搬完 `git diff --stat` 行数应 ≈ 原文件行数 + 样板头 |
| ④ 并行中间状态 | `admin.py` 与 `admin/` 目录同名共存时包优先于模块,语义陷阱 | 批次见下:新建子模块(batch 1,各文件互不重叠可并行)→ **同一提交内**删 `admin.py` + 建 `__init__.py`(batch 2,单代理串行)→ 验证(batch 3)。绝不允许 `admin.py` 与 `admin/__init__.py` 跨批次共存 |
| ⑤ 孤儿文件/死代码 | 明确:**原 `admin.py` 删除**,shim 角色由 `admin/__init__.py` 承担(包替换模块,import 路径不变,无需另留 `.py` 壳) | batch 3 验证 `git status` 无未跟踪残留;本机 `find rpg -name "__pycache__" -path "*api*"` 清缓存(旧 admin.pyc 与新包并存会困惑本地 dev) |
| 循环导入 | 新子模块仅依赖 `_deps`/`db`/`dmca`/`achievements`(均无反向依赖 api.admin);`_common` 不 import 任何兄弟子模块 | 无环。`__init__.py` 先建 `router` 再 import 子模块,与 `api/__init__.py` 同构 |
| 模块级单例/注册顺序 | 38 条路由 path 全唯一,include 顺序不影响匹配;`router` 单例改为聚合树,FastAPI `include_router` 语义等价 | batch 3 用路由清单对账(见下) |

## 6. 串行批次划分(供执行代理照抄)

- **Batch 1(可 6 路并行,文件互不重叠)**:新建 `admin/_common.py`、`users.py`、`observability.py`、`platform_config.py`、`trust_safety.py`、`allowlist.py`、`achievements.py`,按 §4 清单逐字搬运。此时 `admin.py` 原样未动,仓库仍可运行(新目录无 `__init__.py`,不是包,不会遮蔽 `admin.py`——但**不得提交**此中间态)。
- **Batch 2(单代理串行)**:`git rm rpg/platform_app/api/admin.py` + 新建 `admin/__init__.py`(§3 骨架)。同一提交完成。
- **Batch 3(验证)**:
  1. `python -m py_compile rpg/platform_app/api/admin/*.py`
  2. 路由对账(拆分前后各跑一次,diff 必须为空):
     `python -c "from platform_app.main import app; [print(r.methods, r.path) for r in app.routes]" | grep -E "admin|internal" | sort`
     (按本机测试 DB 配方起 venv;预期 38+3 条 admin 路径不变,含 frontend_routes 的 3 条)
  3. 全量 pytest(本机一次性 PG 配方);admin 无直接测试,回归面来自 import 链
  4. `grep -rn "api\.admin" rpg/ --include="*.py"` 确认仅剩 `api/__init__.py:18` 一处消费
  5. 行数对账:`wc -l rpg/platform_app/api/admin/*.py` 总和 ≈ 1464 + 各文件样板头(~10 行/文件)

## 7. 残余风险(低)

- **OSS cherry-pick 冲突面**:本仓库与 OSS fork 双线同步,文件改名/删除会让后续 cherry-pick 在 admin.py 上撞「modify/delete」冲突。建议拆分提交独立成单 commit、message 标注「mechanical split, no logic change」,并尽快同步到 OSS main,缩小分叉窗口。**这是本拆分唯一实质成本,也是 priority=low 的主因之一**——宜挑两线无 admin.py 在途改动的空窗执行。
- 生产部署是 `git pull + restart`(systemd 裸机),Python 源码替换无构建步骤,删文件 + 新包随 pull 原子生效;但部署后旧 `__pycache__/admin.*.pyc` 与新包同名共存属正常,CPython 对「目录包优先」处理正确,无需手动清(本机 dev 建议清)。
