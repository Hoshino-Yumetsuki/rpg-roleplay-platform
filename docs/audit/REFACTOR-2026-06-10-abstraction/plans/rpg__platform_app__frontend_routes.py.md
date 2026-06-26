# 拆分方案:rpg/platform_app/frontend_routes.py(1047 行)

- **审计日期**:2026-06-10
- **verdict**:needs-refactor
- **priority**:medium(无正确性问题、零 mock.patch 耦合,但已是公认的"杂物抽屉",docstring 自述其存在理由是"避免与 api.py 合并冲突"——该理由如今正是它持续膨胀的原因)
- **effort**:M(机械搬运为主,但必须一次性原子转换 + 三道验证门)

---

## 1. 现状结构图

文件 = 单一 `APIRouter` 上挂 **30 条路由 + 3 个辅助函数**,横跨 **8 个互不相关的业务域**。
挂载方式:`rpg/app.py:463` 在 `platform_router` **之后** include(顺序有语义:历史上靠先挂载的
platform_router 遮蔽过本文件的重复路由,见源码 L313-315 注释)。

```
frontend_routes.py (1047 行)
├── 头部 imports + router = APIRouter()                      L1-38
├── Helpers
│   ├── _bad(msg, status)            ← 全文件 20+ 处调用      L44
│   └── _client_ip(request)          ← ⚠️ 死代码(0 调用)     L48
├── AUTH supplements(5 路由)                                 L55-209
│   /api/auth/password · login-history · sessions(list/revoke/revoke-all)
├── PROFILE supplements(5 路由 + 模块级常量)                  L216-310
│   _UPLOAD_ROOT = Path(__file__)... ← ⚠️ 陷阱②命中点         L216
│   avatar(upload/reset/file) · _ensure_profile_extras_table(空壳,被
│   api/me.py + api/platform.py 惰性导入) · visibility · me/preference
├── ACCOUNT lifecycle(7 路由)                                L324-577
│   export(GET/POST 包装) · deactivate · request-delete · cancel-delete
│   · delete-status · delete(兼容包装)   [api_account_export = 101 行]
├── SAVES supplements(4 路由)                                L583-668
│   delete · rename · activate(跨模块清 app._invalidate_user_cache) · export
├── CARDS(1 路由)  import-json                               L674-695
├── MODELS(2 路由) visibility(admin) · validate              L701-755
├── SEARCH(1 路由 + _SEARCH_SCOPES)  api_search = 185 行     L762-950
├── PLUGINS/SKILLS lists(2 路由)                             L956-969
└── ADMIN(3 路由 + _DEPLOY_CFG_KEY)                          L975-1046
    smtp/test · deployment-config GET/POST
```

### 外部引用面(Grep 实查,全量)

| 引用方 | 引用内容 | 性质 |
|---|---|---|
| `rpg/app.py:463` | `from platform_app.frontend_routes import router` | 模块级,try/except 包裹 |
| `rpg/platform_app/api/me.py:22` | `from ..frontend_routes import _ensure_profile_extras_table` | **函数内惰性导入**(无环) |
| `rpg/platform_app/api/platform.py:50` | 同上 | 函数内惰性导入 |
| `rpg/tools/contract_check.py:41` | `RPG_DIR / "platform_app" / "frontend_routes.py"` | **字面文件路径**(文本扫描,非 import) |
| `rpg/tests/integration/test_security_regressions.py:350,370` | `_SMS_VERIFY_BUCKETS / _SMS_VERIFY_MAX / _check_sms_rate / _SMS_CODE_BUCKETS` | ⚠️ **这 4 个符号已不存在**(L38 注释:SMS stub 上线前已删),两条测试现状即 import 报错,属预存失败,与本次重构无关 |
| `rpg/routes/tavern.py` / `db/migrations.py` / `test_save_activate_switches_runtime.py` / `test_account_lifecycle.py` | 仅注释/文档性提及 | 无代码耦合 |

### mock.patch 点清单(陷阱①,Grep 实查)

`grep -rn "patch(\|monkeypatch.setattr" rpg/tests/ | grep frontend_routes` → **0 命中**。
全仓库不存在任何 `mock.patch("platform_app.frontend_routes.*")` 或 `monkeypatch.setattr` 指向本模块。
测试侧对本文件的覆盖全部走 HTTP client(`test_account_lifecycle.py`、`test_save_activate_switches_runtime.py` 等),
对拆分天然免疫。**patch_points = 0**。唯二的符号级 import(SMS 测试)引用的是已删符号,本来就是坏的。

---

## 2. 内聚簇分析

8 个簇之间**零共享状态**(唯一共享物是 `_bad` helper 和来自 `.api`/`.db` 的公共依赖),
簇内有真实耦合(`api_account_export_post → api_account_export`、`api_account_delete → api_account_request_delete`、
avatar 三路由共享 `_UPLOAD_ROOT`)。这是教科书式的"按域垂直切分"场景。

### ≥80 行巨型函数单独评估

| 函数 | 行数 | 形态 | 结论 |
|---|---|---|---|
| `api_search` | 185 | **平行段落表**:6 个 scope 块(scripts/saves/cards/worldbook/memories/npc_cards),每块独立 query→append,各有自己的 try/except 边界,无流水线依赖 | **不拆**。属"纯数据表型"——拆成 6 个 `_search_xxx(db, user, pattern)` 会移动 try/except 边界,收益仅美观。整函数原样搬入 `search.py` |
| `api_account_export` | 101 | 弱流水线(查 9 张表 → 组 payload → json.dumps → zip → stream),但全程直线、内嵌局部 helper(`_to_list/_to_dict/_default`),无复用点 | **不拆**。原样搬入 `account_lifecycle.py`;若未来接 B12 邮件异步化再做阶段化 |

本轮**只做模块级垂直切分,不做任何函数级改写**(陷阱③)。

---

## 3. 目标布局:同名包原地转换(module → package)

**核心决策:把 `frontend_routes.py` 转换为 `frontend_routes/` 包,dotted path 不变。**
这样 `app.py` / `me.py` / `platform.py` 的 import **一行都不用改**,re-export shim 就是包的 `__init__.py` 本身。
命名与聚合方式完全复刻本包既有惯例 `platform_app/api/__init__.py`(sub-router 先 import 再 include + 末尾兼容 re-export + `# ruff: noqa: F401`)。

**否决的备选**:
- 并入 `platform_app/api/` 各主题文件 → 改变 router 注册顺序与挂载层级(platform_router 先挂、frontend_router 后挂的遮蔽语义会被破坏),且与正在并行的审计工作流冲突面大。否决。
- 迁入 `rpg/routes/`(Phase 1.1 试点包)→ 那是 app.py 游戏控制台路由的迁移目标,层不同。否决。

```
rpg/platform_app/frontend_routes/          (新包,替换同名 .py)
├── __init__.py            ~45 行  聚合 + 兼容 re-export(= shim)
├── _helpers.py            ~15 行  _bad · _client_ip
├── auth_sessions.py      ~170 行  5 条 /api/auth/* 路由
├── profile.py            ~110 行  _UPLOAD_ROOT + avatar×3 + _ensure_profile_extras_table
│                                  + visibility + me/preference
├── account_lifecycle.py  ~260 行  7 条 /api/account/* 路由
├── saves_cards.py        ~135 行  4 条 /api/saves/* + import-json
├── search.py             ~205 行  _SEARCH_SCOPES + api_search
├── models_capabilities.py ~90 行  models visibility/validate + plugins + skills
└── admin.py               ~85 行  smtp/test + _DEPLOY_CFG_KEY + deployment-config×2
```

每个子模块:自带 `router = APIRouter()`,文件头 import 只取该簇实际所需(unused 的 `threading`、`expose` 自然消亡,见 §6)。

### `__init__.py`(即 re-export shim)规范文本

```python
"""platform_app.frontend_routes — 前端补充路由,按主题拆 sub-router。

原单文件 frontend_routes.py(1047 行)于 2026-06 拆分为本包;
dotted path 不变,外部 `from platform_app.frontend_routes import router` 照常工作。
"""
# ruff: noqa: F401
from fastapi import APIRouter

router = APIRouter()

from .auth_sessions import router as _auth_sessions_router
from .profile import router as _profile_router
from .account_lifecycle import router as _account_router
from .saves_cards import router as _saves_cards_router
from .models_capabilities import router as _models_caps_router
from .search import router as _search_router
from .admin import router as _admin_router

# include 顺序 = 原文件路由注册顺序(auth→profile→account→saves/cards→models→search→plugins/skills→admin)
router.include_router(_auth_sessions_router)
router.include_router(_profile_router)
router.include_router(_account_router)
router.include_router(_saves_cards_router)
router.include_router(_models_caps_router)   # models 在 search 前,与原文件一致
router.include_router(_search_router)
router.include_router(_admin_router)

# 兼容 re-export(陷阱①保险:外部惰性导入 + 防未来符号级引用)
from ._helpers import _bad, _client_ip
from .profile import _UPLOAD_ROOT, _ensure_profile_extras_table
from .search import _SEARCH_SCOPES
from .admin import _DEPLOY_CFG_KEY
```

注:plugins/skills 两条在原文件位于 search 之后、admin 之前,归入 `models_capabilities.py` 后其注册位置
提前到 search 前。**30 条路由 path+method 全部唯一、互不冲突(已核)**,FastAPI 首匹配语义下注册顺序
在无重复 path 时无行为差异;若执行代理想做到 100% 字节级等价,可把 plugins/skills 单独放
`capabilities.py` 并在 include 链中排到 search 之后——二选一,默认取前者(少一个文件)。

---

## 4. 可机械执行的搬运清单(符号名 → 目标文件)

**铁律:逐字搬运、禁止改写函数体逻辑**(陷阱③)。唯一允许的两类改动:① 各文件头部 import 重组;② §5 列出的 `_UPLOAD_ROOT` 一处 parent 链修正。

| # | 符号(@原行号) | 目标文件 |
|---|---|---|
| 1 | `_bad` @44 | `_helpers.py` |
| 2 | `_client_ip` @48 | `_helpers.py`(死代码,保留待批次3处置) |
| 3 | `api_change_password` @56 | `auth_sessions.py` |
| 4 | `api_login_history` @89 | `auth_sessions.py` |
| 5 | `api_list_sessions` @142 | `auth_sessions.py` |
| 6 | `api_revoke_session` @175 | `auth_sessions.py` |
| 7 | `api_revoke_all_sessions` @198 | `auth_sessions.py` |
| 8 | `_UPLOAD_ROOT` @216 | `profile.py`(⚠️ 唯一允许改写点,见 §5) |
| 9 | `api_upload_avatar` @220 | `profile.py` |
| 10 | `api_reset_avatar` @247 | `profile.py` |
| 11 | `api_avatar_file` @256 | `profile.py` |
| 12 | `_ensure_profile_extras_table` @266 | `profile.py`(必须同时在 `__init__.py` re-export) |
| 13 | `api_profile_visibility` @272 | `profile.py` |
| 14 | `api_save_preference` @290 | `profile.py` |
| 15 | `api_account_export` @325 | `account_lifecycle.py` |
| 16 | `api_account_export_post` @430 | `account_lifecycle.py`(调用 #15,同文件) |
| 17 | `api_account_deactivate` @437 | `account_lifecycle.py` |
| 18 | `api_account_request_delete` @452 | `account_lifecycle.py` |
| 19 | `api_account_cancel_delete` @520 | `account_lifecycle.py` |
| 20 | `api_account_delete_status` @542 | `account_lifecycle.py` |
| 21 | `api_account_delete` @575 | `account_lifecycle.py`(调用 #18,同文件) |
| 22 | `api_save_delete` @584 | `saves_cards.py` |
| 23 | `api_save_rename` @599 | `saves_cards.py` |
| 24 | `api_save_activate` @621 | `saves_cards.py`(体内惰性 `import app as _ui` 原样保留) |
| 25 | `api_save_export` @646 | `saves_cards.py` |
| 26 | `api_card_import_json` @675 | `saves_cards.py` |
| 27 | `api_models_visibility` @702 | `models_capabilities.py` |
| 28 | `api_models_validate` @737 | `models_capabilities.py` |
| 29 | `_SEARCH_SCOPES` @762 | `search.py` |
| 30 | `api_search` @766 | `search.py`(185 行整体原样,不分解) |
| 31 | `api_plugins` @957 | `models_capabilities.py` |
| 32 | `api_skills_list` @965 | `models_capabilities.py` |
| 33 | `api_admin_smtp_test` @976 | `admin.py` |
| 34 | `_DEPLOY_CFG_KEY` @997 | `admin.py` |
| 35 | `api_admin_deployment_config_get` @1001 | `admin.py` |
| 36 | `api_admin_deployment_config_set` @1016 | `admin.py` |

各子模块头部 import 模板(按需删减):
`from fastapi import APIRouter, HTTPException, Request` · `from fastapi.responses import FileResponse, StreamingResponse` ·
`from .. import auth as _auth` · `from ..api import SESSION_COOKIE, _delete_session_cookie, json_response, require_user` ·
`from ..db import connect, init_db` · `from ..security import hash_password, verify_password` · `from ._helpers import _bad` ·
标准库 `csv/io/json/os/time/datetime` 按簇取用。函数体内的惰性 import(`from .auth import _hash_token`、
`from psycopg.types.json import Jsonb`、`from . import branches`、`from . import user_cards`、`from model_registry import …`、
`from model_probe import …`、`from tools_dsl.tool_registry import tool_payload`、`import app as _ui`)**随函数体逐字带走,不上提**。

### 仓库内唯一需要同步修改的外部文件

`rpg/tools/contract_check.py:41`(以及 L5 docstring):

```python
# 原
RPG_DIR / "platform_app" / "frontend_routes.py",
# 改为(包内全部子模块)
*sorted((RPG_DIR / "platform_app" / "frontend_routes").glob("*.py")),
```

不改则 contract_check 静默扫不到这 30 条后端路由,drift 报告会假报"前端调用了不存在的后端端点"。

---

## 5. Path(__file__) 错位清单(陷阱②,逐处列全)

**全文件仅 1 处**,但必中:

- `L216:  _UPLOAD_ROOT = Path(__file__).resolve().parent.parent / "platform_data" / "avatars"`
  - 原位置 `rpg/platform_app/frontend_routes.py` → `parent.parent` = `rpg/` → 解析为 `rpg/platform_data/avatars` ✅
  - 新位置 `rpg/platform_app/frontend_routes/profile.py`(深一层)→ `parent.parent` = `rpg/platform_app/` ❌(头像静默写错目录、历史头像 404)
  - **修正(唯一允许的逻辑改动)**:`Path(__file__).resolve().parent.parent.parent / "platform_data" / "avatars"`,并在行尾加注释 `# 包化后多一层 parent`
  - **验证**:批次2 中 `python -c "from platform_app.frontend_routes.profile import _UPLOAD_ROOT; print(_UPLOAD_ROOT)"` 必须输出 `…/rpg/platform_data/avatars`

其余:`api_save_activate` 体内 `import app as _ui` 是绝对导入(依赖 sys.path 含 `rpg/`),与文件物理位置无关,不受影响。无其他相对路径/`__file__` 用法。

---

## 6. 风险核查与串行批次

### 循环导入

- 子模块模块级 `from ..api import …`:与现状完全相同(原文件 L27 已如此),`platform_app.api` 不在模块级反向 import frontend_routes(me.py/platform.py 均为**函数内**惰性导入)→ 无环。
- `__init__.py` import 子模块、子模块 import `._helpers`(叶子,零依赖)→ 无环。
- 结论:不引入新环。

### 模块级单例 / import 副作用

- 每个子模块各自 `router = APIRouter()`,装饰器注册发生在子模块 import 时;`__init__.py` 的 import 顺序决定 include 顺序,§3 已固定为原文件顺序。30 条路由 path+method 无重复,顺序无行为语义,但仍按原序排列以保守。
- `app.py` 的挂载点(platform_router 先、frontend_router 后)**不动**,历史遮蔽语义不变。
- `_UPLOAD_ROOT`(import 时求值的 Path)、`_SEARCH_SCOPES`、`_DEPLOY_CFG_KEY` 均为只读常量,随簇搬运无副作用。

### 五大陷阱对照小结

| 陷阱 | 本案命中情况 | 对策 |
|---|---|---|
| ① patch 命名空间穿透 | **0 个 mock.patch 点**(Grep 实查);2 处测试符号 import 指向已删 SMS 符号,本来就坏 | `__init__.py` 仍 re-export 全部模块级符号兜底;SMS 测试处置归批次3 |
| ② Path(__file__) | 1 处:`_UPLOAD_ROOT` | §5 修正 + 启动断言验证 |
| ③ 执行代理顺手简化 | `api_search`(185行)/`api_account_export`(101行)最易被"优化" | 铁律写入搬运清单:逐字搬运,函数体零改动;搬完 `git diff --stat` 行数对账(新包总行数 ≈ 1047±10%) |
| ④ 并行中间状态 | `frontend_routes.py` 与 `frontend_routes/` **同名不能共存**,转换不可拆成并行批次 | 批次1 由单一代理原子完成(建包+搬运+删旧文件,一个 commit) |
| ⑤ 孤儿文件 | 旧 `frontend_routes.py` | **明确:删除**(不保留 .py shim——包 `__init__.py` 即 shim,同 dotted path);contract_check 路径同步改,防文本扫描孤儿引用 |

### 串行批次划分

- **批次 1(单代理,原子,sonnet 可执行)**:`git rm rpg/platform_app/frontend_routes.py` + 新建包及 9 个文件,按 §4 清单逐字搬运,§5 一处修正。同 commit 内完成,中途不可插入其他批次。
- **批次 2(验证门,依赖批次1)**:
  1. `python -m compileall rpg/platform_app/frontend_routes/`
  2. 路由表等价性 diff(拆分前先在旧文件上跑一次留底):
     `python -c "from platform_app.frontend_routes import router; print('\n'.join(sorted(f'{sorted(r.methods)} {r.path}' for r in router.routes)))"` — 前后输出必须逐字节一致(30 条)。
  3. 兼容面 smoke:`from platform_app.frontend_routes import router, _ensure_profile_extras_table, _bad` 不抛错;`_UPLOAD_ROOT` 路径断言(§5)。
  4. pytest:`rpg/tests/test_account_lifecycle.py`、`rpg/tests/integration/test_save_activate_switches_runtime.py`、`rpg/tests/integration/test_security_regressions.py`(注:其中 SmsEndpointsRateLimited 两条为预存失败,拆分前后均失败才算"无回归")。
  5. 同 commit 或紧随:contract_check.py 路径更新 + `python -m tools.contract_check` 跑通。
- **批次 3(可选清理,独立 commit,可延后)**:
  - 删除死代码:`_client_ip`(0 调用;`api/_deps.py` 另有同名实现)、确认 `threading`/`expose` 未随搬运复活;
  - 处置 `test_security_regressions.py:350,370` 两条引用已删 SMS 符号的坏测试(删除或 skip+注明),需用户确认——**不属于本重构,单独决策**。

### 残余风险

低。外部 import 面只有 3 个文件且 dotted path 不变;真正的隐性耦合只有 contract_check 的字面路径(已列入批次2)。最大人为风险是陷阱③(两个百行函数被执行代理改写),靠"逐字搬运 + 行数对账 + 路由表 diff"三道闸拦截。
