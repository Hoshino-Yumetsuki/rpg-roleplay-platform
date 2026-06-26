# 拆分方案:rpg/platform_app/auth.py(1416 行)

- **Verdict**: needs-refactor
- **Priority**: medium(功能正常、安全敏感、测试 pin 多 → 不紧急但该拆;文件仍在持续长大,越晚拆 patch 点越多)
- **Effort**: M(机械搬运 + 35 个测试 patch 点同步改,5 个串行批次,每批可独立验绿)
- **方式**: 模块 → 包(`auth.py` → `auth/` 包 + `__init__.py` 永久 façade),对所有外部 importer 零感知

---

## 1. 现状结构图(精读 + Grep 实查)

1416 行单文件,7 个可清晰辨认的职责簇,共享 14 个模块级可变状态对象:

```
auth.py
├─ [A] 限流/锁定状态机(Redis 主路径 + 进程内回落双实现)
│   RateLimited(@85) _bucket_key(@93) _check_rate_limit(@97) _record_login_fail(@129)
│   _record_login_success(@168) _write_audit(@186) admin_unlock(@219)
│   _verify_locked(@546) _record_verify_fail(@556) _clear_verify_fail(@574)
│   状态: _FAIL_BUCKETS_IP/_USER, _LOCKED_UNTIL_IP/_USER, _VERIFY_FAIL_BUCKETS,
│         _VERIFY_LOCKED_UNTIL, _FAIL_BUCKETS, _LOCKED_UNTIL(legacy), _FAIL_LOCK
│   常量: LOGIN_MAX_FAILS, LOGIN_LOCKOUT_SEC, LOGIN_WINDOW_SEC, _IP_*, _USER_*, _VERIFY_*
├─ [B] pending 注册暂存(SEC(H-7) 安全缝:Redis TTL + 进程内 dict)
│   _pending_redis_key(@425) _pending_store_set(@429) _pending_store_get(@443)
│   _encode_pending_register(@467) _decode_pending_register(@476)
│   状态: _PENDING_REGISTER, _PENDING_TTL_SEC, _PENDING_REGISTER_UA_PREFIX
├─ [C] 两步注册流(register@261=157行, confirm_email_verification@586=130行,
│   resend_verification_code@994, _check_invite_code(@504), _bootstrap_admin_allowed(@243))
│   状态: _RESEND_LAST
├─ [D] session 管理(_hash_token@718, _issue_session@723, user_from_token@951,
│   logout@941, get_user@971, update_profile@980, SESSION_DAYS)
├─ [E] 密码/邮箱码登录(login@869=70行, request_login_code@749=70行, confirm_login_code@821)
├─ [F] magic-link/passwordless(consume_magic_token@1137, request_passwordless_code@1164,
│   verify_passwordless_and_login@1196=86行, login_via_magic_token@1284=72行)
├─ [G] 密码重置(_check_reset_rate@1058, request_password_reset@1080=55行,
│   confirm_password_reset@1358=58行; 状态: _RESET_RATE, _RESET_RATE_LOCK, _RESET_MAX_PER_10MIN)
└─ [杂] _mask_email(@211, C/E 共用), _row_get(@494, **死代码,全仓 0 调用点**),
       MIN_PASSWORD_LENGTH(@42, C/G + api/auth.py + frontend_routes.py 共用)
```

### 外部 importer(Grep 实查,全部经由 `platform_app.auth` 命名空间)

| 文件 | 用到的符号 |
|---|---|
| `rpg/core/security.py` | re-export shim:RateLimited, admin_unlock, get_user, login, logout, register, update_profile, user_from_token |
| `rpg/platform_app/api/auth.py` | MIN_PASSWORD_LENGTH, RateLimited, `_check_rate_limit`(L36), `_record_login_fail`(L84), 全部 17 个流程函数(`_auth.X` 属性访问) |
| `rpg/platform_app/api/platform.py` | update_profile |
| `rpg/platform_app/api/_deps.py` | SESSION_DAYS, user_from_token(属性访问 `auth.user_from_token`) |
| `rpg/platform_app/frontend_routes.py` | MIN_PASSWORD_LENGTH(L62-63), `from .auth import _hash_token`(L80/145/182/201) |
| `rpg/tests/*` | 见 §5 patch 点清单 |
| `rpg/claude_design_upload/current_code/...` | 历史快照目录,非 import 可达,**不动** |

无任何 `mock.patch("platform_app.auth.X")` 字符串式 patch(Grep 实查为 0);测试全部用 `patch.object` / `monkeypatch.setattr` / 直接属性赋值 / 模块状态原地变更。

---

## 2. 内聚簇分析与判定理由

**判 needs-refactor 的依据**:
1. 基础设施([A] 限流、[B] pending 存储、审计)与领域流程([C]-[G])混在一层;[A] 的 Redis-or-进程内双实现模式重复了 4 遍(login fail / verify fail / reset rate / resend cooldown),拆出后才有统一抽象的落点(本次不做统一,只做搬运,见 §8 follow-up)。
2. 各流程簇之间几乎零互调(register 不调 login,reset 不调 passwordless),仅共享 [A]/[B]/[D] 的少量函数——边界天然干净,拆分不需要改任何函数体逻辑。
3. 该文件历史上每加一种登录方式就 +200~300 行(magic-link、passwordless 都是后加的),不拆会继续膨胀。

**为什么不是 acceptable**:它不是追加式账本/纯数据表/声明式注册——是 7 个活跃演进的业务流程共用一个命名空间,且安全修复(SEC H-6/H-7/L-2…)反复手术于此,模块边界能直接缩小未来每次安全手术的 blast radius。

**为什么不是 leave-as-is**:风险可控——所有外部消费都走 `platform_app.auth` 命名空间属性访问或 `from platform_app.auth import X`,包化 + façade 完整 re-export 即可 100% 保持;唯一硬成本是 35 个测试 patch 点要同步改(§5 已逐行列全),全部机械可执行。

### ≥80 行巨型函数逐个评估(是否拆阶段函数)

| 函数 | 行数 | 判定 | 理由 |
|---|---|---|---|
| `register` | 157 | **本次不拆体** | 流水线型(校验→payload→DB 闸→写验证码→暂存→本地模式短路→发邮件),理论可拆 `_registration_gates(db,...)`,但整段在事务语义和安全注释强耦合下,verbatim 搬运优先;留 follow-up |
| `confirm_email_verification` | 130 | **本次不拆体** | 单事务流水线,两个近似 INSERT 分支(allow_admin)是刻意的 SQL 差异,拆阶段函数会诱发执行代理"顺手合并"两分支 → 高危 |
| `verify_passwordless_and_login` | 86 | **本次不拆体,记 follow-up** | 与 `login_via_magic_token` 重复 ~40 行"查/建白名单用户"块,值得抽 `_find_or_create_allowlisted_user(db, email_norm, ip)`,但这是行为级重构,需独立测试,**不混入机械搬运批次** |
| `login_via_magic_token` | 72(<80 但同上) | 同上 | 同上 |

---

## 3. 目标布局

```
rpg/platform_app/auth/
├─ __init__.py        # 永久 façade:逐符号显式 re-export(含全部下划线符号),~110 行
├─ _common.py         # MIN_PASSWORD_LENGTH, _mask_email, _row_get(暂留,Batch 5 删)   ~30 行
├─ _ratelimit.py      # 簇 [A] 全部(含 _write_audit、admin_unlock、legacy dict)        ~260 行
├─ _pending.py        # 簇 [B] 全部                                                      ~90 行
├─ _sessions.py       # 簇 [D] 全部                                                      ~95 行
├─ _registration.py   # 簇 [C] 全部 + _RESEND_LAST                                       ~420 行
├─ _login.py          # 簇 [E] 全部                                                      ~200 行
├─ _passwordless.py   # 簇 [F] 全部                                                      ~225 行
└─ _reset.py          # 簇 [G] 全部                                                      ~155 行
```

命名遵循本包已有惯例:`platform_app/` 下子包(`api/`、`db/`、`knowledge/`、`achievements/`)+ 私有实现模块前导下划线(`api/_deps.py` 先例)。注意 `platform_app/api/auth.py`(HTTP 层)与本包同名不冲突——import 路径 `platform_app.auth` 不变。

### 各模块 import 头(规定死,执行代理照抄)

- 外部依赖一律 **符号 import**(与现状一致,保证函数体 bare-name 调用不动):`from ..db import connect, init_db`、`from ..security import <按需>`、`from core.config import ...`、`import redis_bus`(函数体内的 lazy `import redis_bus` 原样保留)。
- 包内兄弟依赖也用 **符号 import**(`from ._ratelimit import _check_rate_limit` 等)——这决定了测试 patch 目标 = **消费方模块**(见 §5)。
- `__init__.py` 只做 `from ._xxx import (...)` 显式列名 re-export,**不写任何实现**,并设 `__all__`。

---

## 4. 搬运清单(符号 → 目标文件;逐字搬运、禁止改写逻辑)

> **铁律③**:全部函数/类/常量/dict **逐字 cut-paste**,不允许重命名、不允许合并相似分支、不允许"顺手"改 SQL/注释/错误文案。唯一允许的体内编辑是 §4.1 列出的相对 import 点号升级,一共 7 处,逐处列死。

| 符号 | 目标 |
|---|---|
| `MIN_PASSWORD_LENGTH`(含其 `from core.config import min_password_length` 来源行) | `_common.py` |
| `_mask_email` | `_common.py` |
| `_row_get` | `_common.py`(死代码,Batch 5 删除) |
| `LOGIN_MAX_FAILS, LOGIN_LOCKOUT_SEC, LOGIN_WINDOW_SEC`(含 core.config 来源 import) | `_ratelimit.py` |
| `_IP_MAX_FAILS, _IP_WINDOW_SEC, _USER_MAX_FAILS, _USER_WINDOW_SEC` | `_ratelimit.py` |
| `_VERIFY_MAX_FAILS, _VERIFY_WINDOW_SEC` | `_ratelimit.py` |
| `_FAIL_BUCKETS_IP, _FAIL_BUCKETS_USER, _LOCKED_UNTIL_IP, _LOCKED_UNTIL_USER` | `_ratelimit.py` |
| `_VERIFY_FAIL_BUCKETS, _VERIFY_LOCKED_UNTIL` | `_ratelimit.py` |
| `_FAIL_BUCKETS, _LOCKED_UNTIL`(legacy,admin_unlock 仍 pop) | `_ratelimit.py` |
| `_FAIL_LOCK` | `_ratelimit.py` |
| `class RateLimited` | `_ratelimit.py` |
| `_bucket_key, _check_rate_limit, _record_login_fail, _record_login_success` | `_ratelimit.py` |
| `_write_audit`(含 `Jsonb` import;调用方全在本模块) | `_ratelimit.py` |
| `admin_unlock` | `_ratelimit.py` |
| `_verify_locked, _record_verify_fail, _clear_verify_fail` | `_ratelimit.py` |
| `_PENDING_REGISTER_UA_PREFIX, _PENDING_REGISTER, _PENDING_TTL_SEC` | `_pending.py` |
| `_pending_redis_key, _pending_store_set, _pending_store_get` | `_pending.py` |
| `_encode_pending_register, _decode_pending_register` | `_pending.py` |
| `SESSION_DAYS` | `_sessions.py` |
| `_hash_token, _issue_session, user_from_token, logout, get_user, update_profile` | `_sessions.py` |
| `_bootstrap_admin_allowed, register, _check_invite_code` | `_registration.py` |
| `confirm_email_verification, resend_verification_code, _RESEND_LAST` | `_registration.py` |
| `login, request_login_code, confirm_login_code` | `_login.py` |
| `consume_magic_token, request_passwordless_code` | `_passwordless.py` |
| `verify_passwordless_and_login, login_via_magic_token` | `_passwordless.py` |
| `_RESET_RATE, _RESET_RATE_LOCK, _RESET_MAX_PER_10MIN` | `_reset.py` |
| `_check_reset_rate, request_password_reset, confirm_password_reset` | `_reset.py` |
| `import os`(L4,全文件 0 使用,死 import) | 不搬,Batch 5 删 |
| `verify_password`(L19 从 .security 引入,体内 0 使用) | 不搬入任何子模块;façade 直接 `from ..security import verify_password` 保住 `from platform_app.auth import verify_password` 兼容 |

包内跨模块符号 import(决定 patch 目标,照抄):
- `_registration.py` ← `from ._pending import _pending_store_set, _pending_store_get, _encode_pending_register, _decode_pending_register`;`from ._ratelimit import _verify_locked, _record_verify_fail, _clear_verify_fail`;`from ._sessions import SESSION_DAYS, _hash_token`;`from ._common import MIN_PASSWORD_LENGTH, _mask_email`
- `_login.py` ← `from ._ratelimit import _check_rate_limit, _record_login_fail, _record_login_success, RateLimited(如体内需要)`;`from ._sessions import SESSION_DAYS, _hash_token, _issue_session`;`from ._common import _mask_email`
- `_passwordless.py` ← `from ._ratelimit import _check_rate_limit, _record_login_fail, _record_login_success`;`from ._sessions import _issue_session`
- `_reset.py` ← `from ._common import MIN_PASSWORD_LENGTH`
- 依赖图为 DAG:`_common/_pending/_ratelimit/_sessions`(叶)← `_registration/_login/_passwordless/_reset`(流程)← `__init__`。**无环**(已核:无叶模块反向 import 流程模块;无子模块 import 包 façade)。

### 4.1 唯一允许的体内编辑:相对 import 点号升级(陷阱②的本仓变体)

文件无 `Path(__file__)`、无相对文件路径、无 `os.` 使用(Grep 实查为 0)——经典陷阱②不命中。但模块下沉一层后,**相对 import 的 `.` 语义会变**,以下 7 处必须 `.` → `..`,除此之外函数体一字不改:

| 原行号 | 原文 | 改为 | 落点 |
|---|---|---|---|
| L14 | `from .db import connect, init_db` | `from ..db import connect, init_db` | 各子模块头部(按需) |
| L15-25 | `from .security import (...)` | `from ..security import (...)` | 各子模块头部(按需拆分名单) |
| L411(register 体内) | `from .email import send_verification_email, EmailSendError` | `from ..email import ...` | `_registration.py` |
| L812(request_login_code 体内) | `from .email import send_login_code_email, EmailSendError` | `from ..email import ...` | `_login.py` |
| L1040(resend_verification_code 体内) | `from .email import send_verification_email, EmailSendError` | `from ..email import ...` | `_registration.py` |
| L1128(request_password_reset 体内) | `from .email import send_password_reset_email, EmailSendError` | `from ..email import ...` | `_reset.py` |
| L1188(request_passwordless_code 体内) | `from .email import send_login_code_email, EmailSendError` | `from ..email import ...` | `_passwordless.py` |

(`import redis_bus`、`from core.config import ...`、`import datetime/json/secrets...` 均为绝对 import,原样照抄。)

### 4.2 façade `__init__.py` re-export 全名单

```python
from ._common import MIN_PASSWORD_LENGTH, _mask_email, _row_get   # _row_get 于 Batch 5 随删
from ._ratelimit import (
    RateLimited, admin_unlock,
    _bucket_key, _check_rate_limit, _record_login_fail, _record_login_success, _write_audit,
    _verify_locked, _record_verify_fail, _clear_verify_fail,
    LOGIN_MAX_FAILS, LOGIN_LOCKOUT_SEC, LOGIN_WINDOW_SEC,
    _IP_MAX_FAILS, _IP_WINDOW_SEC, _USER_MAX_FAILS, _USER_WINDOW_SEC,
    _VERIFY_MAX_FAILS, _VERIFY_WINDOW_SEC,
    _FAIL_BUCKETS_IP, _FAIL_BUCKETS_USER, _LOCKED_UNTIL_IP, _LOCKED_UNTIL_USER,
    _VERIFY_FAIL_BUCKETS, _VERIFY_LOCKED_UNTIL, _FAIL_BUCKETS, _LOCKED_UNTIL, _FAIL_LOCK,
)
from ._pending import (
    _PENDING_REGISTER, _PENDING_TTL_SEC, _PENDING_REGISTER_UA_PREFIX,
    _pending_redis_key, _pending_store_set, _pending_store_get,
    _encode_pending_register, _decode_pending_register,
)
from ._sessions import (SESSION_DAYS, _hash_token, _issue_session,
                        user_from_token, logout, get_user, update_profile)
from ._registration import (register, confirm_email_verification, resend_verification_code,
                            _check_invite_code, _bootstrap_admin_allowed, _RESEND_LAST)
from ._login import login, request_login_code, confirm_login_code
from ._passwordless import (consume_magic_token, request_passwordless_code,
                            verify_passwordless_and_login, login_via_magic_token)
from ._reset import (_check_reset_rate, request_password_reset, confirm_password_reset,
                     _RESET_RATE, _RESET_RATE_LOCK, _RESET_MAX_PER_10MIN)
# 历史兼容:auth.py 曾把这些名字带进自己命名空间,生产/测试有经由 auth 取用的(connect/init_db/
# hash_password/generate_email_code 被测试 patch;其余防御性保留)
from ..db import connect, init_db
from ..security import (hash_password, normalize_email, normalize_username, verify_password,
                        verify_password_with_rehash, generate_email_code, hash_email_code,
                        verify_email_code, calc_age)
__all__ = [...]  # 上述全部公有名 + 测试触达的下划线名
```

> 注意:façade 上的 `connect/init_db/hash_password/generate_email_code` re-export 只保证 `from platform_app.auth import X` 不炸;**patch 它们不再穿透到子模块**——这正是 §5 必须逐行改 patch 目标的原因,不能心存侥幸。

---

## 5. 测试 patch 点清单(Grep 实查,35 处需改 + 2 处免改)

陷阱①核查结论:无字符串式 `mock.patch("platform_app.auth.X")`;全部是对象式 patch/setattr/属性赋值。**需改 35 行**,按批次归组:

### 5.1 `rpg/tests/test_register_full.py` — 17 处(Batch 2 改 13 处,Batch 3 改 4 处)

注册/验证/重发类 → 新目标 `platform_app.auth._registration`:
- L148 `setattr(auth_mod, "connect", fake_connect)`、L149 `"init_db"`
- L213 `"connect"`、L227 `"init_db"`、L228 `"connect"`
- L251 `"init_db"`、L253 `"connect"`
- L275 `"init_db"`、L278 `"connect"`
- L305 `"init_db"`、L326 `"connect"`
- L338 `"init_db"`、L340 `"connect"`

login 测试 → 新目标 `platform_app.auth._login`(L394/395 注意:`login` 体内 bare-name 调用,符号 import 自 `_ratelimit`,故 patch 必须打在 **`_login` 模块**上):
- L391 `"init_db"`、L392 `"connect"`、L394 `"_check_rate_limit"`、L395 `"_record_login_success"`

改法:文件头(或各测试函数内)`import platform_app.auth._registration as reg_mod` / `import platform_app.auth._login as login_mod`,把对应 setattr 第一参数替换;`auth_mod._PENDING_REGISTER` 等状态访问行**不改**(见 §5.5)。另:L32 `_auth()` helper 内有 `importlib.reload(platform_app.auth)`——该 helper 全文件 0 调用(Grep 实查),不构成风险,但 Batch 2 顺手在其 docstring 标注"包化后 reload 只刷新 façade"或直接删除该死 helper(二选一,倾向删除)。

### 5.2 `rpg/tests/test_register_consent.py` — 2 处(Batch 2)

→ `platform_app.auth._registration`:
- L162 `setattr(auth_mod, "init_db", ...)`、L163 `setattr(auth_mod, "connect", ...)`

### 5.3 `rpg/tests/helpers.py` — 3 处(Batch 2;**最容易被漏的穿透点**)

`register_user` 直接**重绑** façade 属性,搬运后不再穿透到 `_registration` 的全局名 `generate_email_code`,集成测试会收到真随机码而全红:
- L62 `old_generate_email_code = _auth.generate_email_code`
- L63 `_auth.generate_email_code = lambda n_digits=6: code`
- L76 `_auth.generate_email_code = old_generate_email_code`

改为对 `platform_app.auth._registration` 做同样的 save/替换/restore(保持 try/finally 结构不变)。

### 5.4 `rpg/tests/test_password_reset.py` — 13 处(Batch 4)

→ `platform_app.auth._reset`:
- L79 `patch.object(_auth, "connect", ...)`、L80 `"init_db"`、L81 `"_check_reset_rate"`
- L95 `"connect"`、L96 `"init_db"`、L97 `"_check_reset_rate"`
- L127 `"connect"`、L128 `"init_db"`、L129 `"hash_password"`
- L141 `"connect"`、L142 `"init_db"`
- L153 `"connect"`、L154 `"init_db"`

(L81/L97 的 `_check_reset_rate` 与其调用方 `request_password_reset` 同在 `_reset.py`,patch 在 `_reset` 模块上天然穿透 ✓。)

### 5.5 免改但必须逐项验证的状态共享点(re-export 同对象别名,只原地变更、无重绑)

| 文件:行 | 访问 | 为什么免改 |
|---|---|---|
| test_register_full.py L52/53/55/56 | `auth_mod._PENDING_REGISTER.clear()` / `_RESEND_LAST.clear()` | façade 别名与 `_pending`/`_registration` 持同一 dict 对象,`clear()` 原地生效 |
| test_register_full.py L183 | `auth_mod._PENDING_REGISTER.get(...)` | 同上 |
| test_register_full.py L319 | `auth_mod._PENDING_REGISTER[k] = ...` | item 赋值原地生效(非属性重绑) |
| test_register_consent.py L122/L150 | `_PENDING_REGISTER` clear/item 赋值 | 同上 |
| test_password_reset.py L177 | `_auth._RESET_RATE.clear()` | 同上 |
| test_password_reset.py L180/L184 | `from platform_app.auth import _check_reset_rate, _RESET_RATE_LOCK, _RESET_RATE` | façade re-export 保住 import;函数与其状态 dict 同居 `_reset.py`,语义不变 |
| unit/test_verify_bruteforce_guard.py(L15-44 共 ~19 行) | `auth._FAIL_LOCK` with 块、`_VERIFY_FAIL_BUCKETS/_VERIFY_LOCKED_UNTIL` pop、`_verify_locked/_record_verify_fail/_clear_verify_fail/_VERIFY_MAX_FAILS/_VERIFY_WINDOW_SEC` | 函数与全部状态同搬 `_ratelimit.py`,façade 别名同对象 |
| unit/test_security_batch3.py(L20-46 共 ~10 行) | `auth._encode_pending_register/_pending_store_set/_pending_store_get/_decode_pending_register` | 函数与 `_PENDING_REGISTER` 同搬 `_pending.py` |
| integration/test_critical_paths.py L189/190 | `_auth._FAIL_BUCKETS_USER.clear()` / `_LOCKED_UNTIL_USER.clear()` | 同对象别名 |
| integration/test_script_character_cards.py L15 | `from platform_app.auth import _issue_session` | façade re-export |
| unit/test_ensure_default_once_guard.py L21/L37 | `setattr(_deps.auth, "user_from_token", ...)` | `_deps.py` L191 经 `auth.user_from_token` **属性访问**调用 → patch façade 即生效,免改 |

**配套硬规则(写给执行代理)**:任何子模块、任何函数,**永远不得重绑**这些模块级 dict/锁(只许原地变更);否则 §5.5 的同对象别名假设崩塌。现状代码已满足(全文件无 `global X` 重绑,Grep 实查),搬运时不得引入。

### 5.6 生产侧经 façade 的私有符号调用(免改,re-export 覆盖)

- `api/auth.py` L36 `_auth._check_rate_limit`、L84 `_auth._record_login_fail`、L37/145/164/185 `_auth.RateLimited`、L335 `_auth.MIN_PASSWORD_LENGTH`(属性访问,façade 即可)
- `frontend_routes.py` L62/63 `_auth.MIN_PASSWORD_LENGTH`;L80/145/182/201 `from .auth import _hash_token`
- `core/security.py` 8 个公有名 re-export(façade 覆盖,零改动)

---

## 6. 五大陷阱逐条对照

| 陷阱 | 本案核查结果 | 对策 |
|---|---|---|
| ① patch 命名空间穿透 | 无字符串 patch;对象式 patch 35 处会失效(§5.1-5.4 逐行列全),另有 helpers.py 的属性重绑 3 处(§5.3,最隐蔽) | patch 改目标与搬运同批落地、同批验绿;免改点(§5.5)逐项跑对应测试文件确认 |
| ② Path(__file__)/相对路径 | 文件内 0 处 `__file__`、0 处文件路径(Grep 实查);但相对 import 下沉一层共 7 处点号要升级 | §4.1 逐处列死,除此之外体内零编辑 |
| ③ 执行代理顺手简化 | `confirm_email_verification` 的双 INSERT 分支、`verify_passwordless_and_login`/`login_via_magic_token` 的相似块,都是高危"被合并"对象 | §4 铁律:逐字搬运;相似块去重列为 follow-up,本次明令禁止 |
| ④ 并行中间状态 | `__init__.py`(由原 auth.py 改名而来)在每个批次都会被改 | §7 串行批次,单写者,每批一 commit 一验绿,禁止并行执行任何两批 |
| ⑤ 孤儿文件/死代码 | 原 `auth.py` 不会成为孤儿:`git mv` 为 `auth/__init__.py` 永久 façade(明确**保留**,不删除);死代码:`import os`(L4)、`_row_get`(L494,全仓 0 调用)、test_register_full L32 死 helper `_auth()` | Batch 5 专门 commit 删除三者;façade 永久保留并在 docstring 写明"对外唯一入口" |
| 循环导入 | 依赖图为 DAG(§4),子模块不 import 包 façade;体内 lazy `import redis_bus`/`from ..email import` 保持惰性,无 import 期环 | Batch 验证含 `python -c "import platform_app.auth"` 冷启动冒烟 |
| 模块级单例/import 副作用 | 14 个状态对象(§1)各自唯一归属(§4),façade 别名同对象;`MIN_PASSWORD_LENGTH`/`LOGIN_*` 在 import 时读 core.config(现状如此,搬运后仍只读一次,行为不变);无注册表/装饰器注册顺序问题 | 单一归属 + 永不重绑(§5.5 硬规则) |

其它已核风险:
- 子模块 logger 名从 `platform_app.auth` 变为 `platform_app.auth._xxx`——全仓无按该 logger 名的过滤配置(影响仅日志前缀,可接受,记入 changelog)。
- OSS 同步(cherry-pick 流程):模块→包的 `git mv` + 多文件新增会扩大与 OSS fork 的冲突面;建议本重构合入生产后按既有五闸流程整段 cherry-pick,勿与其它 auth 改动交叉。
- 并行审计工作流正在读源码:**本方案仅为文档,未动任何源码**;执行须等审计工作流收尾后再开 Batch 0。

---

## 7. 串行批次划分(每批 = 1 commit,验绿后才许进下一批)

验证门(每批通用):`python -m compileall rpg/platform_app/auth` → `python -c "import platform_app.auth"`(在 rpg/ 的 venv 下)→ 定向 pytest(批内列出)→ Batch 5 后全量 pytest。

- **Batch 0|包化(行为零变)**:`git mv rpg/platform_app/auth.py rpg/platform_app/auth/__init__.py`;仅做 §4.1 的 7 处点号升级。定向测试:test_register_full、test_register_consent、test_password_reset、unit/test_verify_bruteforce_guard、unit/test_security_batch3、integration/test_critical_paths、integration/test_script_character_cards。此时所有 patch 点仍指向 `__init__`,应全绿。
- **Batch 1|抽离叶模块**:新建 `_common.py`、`_pending.py`、`_ratelimit.py`、`_sessions.py`(verbatim cut-paste),`__init__` 补 §4.2 对应 re-export;流程函数仍留在 `__init__`(其符号 import 自新叶模块,bare-name 调用不变)。**本批不改任何测试**(connect/init_db patch 仍打在流程所在的 `__init__` 上,穿透 ✓)。
- **Batch 2|抽离 `_registration.py`** + 同批改:test_register_full 13 处(§5.1 注册类)、test_register_consent 2 处(§5.2)、helpers.py 3 处(§5.3)、删/注记 test_register_full L32 死 helper。定向:test_register_full、test_register_consent、跑 1 个用到 helpers.register_user 的集成测试文件。
- **Batch 3|抽离 `_login.py` + `_passwordless.py`** + 同批改 test_register_full L391/392/394/395(§5.1 login 类)。定向:test_register_full、integration/test_critical_paths。
- **Batch 4|抽离 `_reset.py`** + 同批改 test_password_reset 13 处(§5.4)。定向:test_password_reset。
- **Batch 5|收尾清理**:删 `import os`、删 `_row_get`(及 façade 对应 re-export 行)、补 `__all__` 与 façade docstring;全量 pytest + `grep -rn "platform_app.auth" rpg/ | grep -v __pycache__` 复核引用面 + 前端无关(纯后端)。

回滚策略:任一批红且 10 分钟内定位不了 → `git revert` 该批单 commit 即回到上一绿点(批间无跨文件半成品)。

---

## 8. Follow-up(明确不在本次范围)

1. 限流四件套(login fail / verify fail / reset rate / resend cooldown)统一为一个"Redis-or-进程内"小抽象(拆完后都在 `_ratelimit.py`/各流程内,有了落点;需独立设计 + 测试)。
2. `verify_passwordless_and_login` 与 `login_via_magic_token` 的"查/建白名单用户"~40 行重复块抽 `_find_or_create_allowlisted_user`(行为级重构,独立批次)。
3. `login` 体内手写的会话上限驱逐块与 `_issue_session` 重复(@723 与 @913 几乎同文),可统一改调 `_issue_session`(行为级,独立批次)。
4. `core/security.py` 这个二级 shim 是否还需要(8 个名字、独立于本次)。
