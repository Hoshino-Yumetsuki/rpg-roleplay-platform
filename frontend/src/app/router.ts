// @ts-nocheck
// router.js —— SPA 路径 ↔ Platform page id 映射 + 跨区导航桥。
//
// 全站现在是单页应用(单 index.html + React Router)。三个区:
//   · /login            登录
//   · /platform/<...>   多用户创作工作台(本文件负责其内部 page id ↔ 路径映射)
//   · /console          RPG 游戏控制台
//
// Platform 内部仍用「page id」描述子页(profile / settings-models / saves-branches …);
// 这里把 page id 双向映射到 /platform 下的干净路径:
//   · 首段命名空间用「首个连字符 → 斜杠」规则,保证可逆:
//       settings-models       ↔ /platform/settings/models
//       admin-dmca-takedowns  ↔ /platform/admin/dmca-takedowns  (只换第一个连字符)
//       saves-branches        ↔ /platform/saves/branches
//   · 无连字符的 id 直接作为单段:profile ↔ /platform/(首页)、scripts ↔ /platform/scripts
//
// 导航:
//   · plNavigate(id)   —— platform 内部跳转:走 React Router(URL)+ 派发 pl-navigate(组件 page 状态)
//   · appNavigate(path)—— 跨区跳转(/login、/console、/platform/...):走 React Router,触发懒加载切块
//   · plHardNavigate   —— 整页导航(登出等需要清空所有运行时状态的场景)
//
// 后端 _SPAStaticFiles 对「无扩展名、非 /api」路径回退 index.html,深链/刷新不 404。

export const PL_HASH_ALIASES = { branches: 'saves-branches', 'settings-deploy': 'admin-deploy' };

const PLATFORM_BASE = '/platform';

// React Router 的 navigate(由 main.jsx 在挂载后注入);未注入时退回 history API / location。
let __routerNavigate = null;
export function setRouterNavigate(fn) { __routerNavigate = fn; }

// page id → 路径段(首个连字符换成斜杠)
function idToSeg(id) {
  const i = id.indexOf('-');
  return i === -1 ? id : id.slice(0, i) + '/' + id.slice(i + 1);
}
// 路径段 → page id(首个斜杠换回连字符)
function segToId(seg) {
  const i = seg.indexOf('/');
  return i === -1 ? seg : seg.slice(0, i) + '-' + seg.slice(i + 1);
}

// page id → 完整路径。首页 profile 规范化为 /platform/。
export function plPageToPath(id) {
  const pid = id || 'profile';
  if (pid === 'profile') return PLATFORM_BASE + '/';
  return PLATFORM_BASE + '/' + idToSeg(pid);
}

// 当前 URL → page id(无效返回 null;/platform 根 / 入口 → 'profile')。
export function plPathToPage(validIds) {
  let raw = '';
  try { raw = decodeURIComponent(location.pathname || '/'); }
  catch (_) { raw = location.pathname || '/'; }
  raw = raw.replace(/^\/+/, '').replace(/\/+$/, '');   // 去首尾斜杠
  raw = raw.replace(/^platform(\/|$)/, '');            // 去掉 platform 段前缀
  // 旧 Platform.html#x 深链 / 残留 hash → 从 hash 抢救
  if ((!raw || raw === 'platform') && location.hash) {
    raw = location.hash.replace(/^#/, '').split('?')[0];
  }
  if (!raw || raw === 'platform') return 'profile';
  let id = segToId(raw);
  id = PL_HASH_ALIASES[id] || id;
  if (validIds && !validIds.includes(id)) return null;
  return id;
}

// Platform 内部编程跳转:写 URL(React Router)+ 通知 PlatformApp。search 形如 '?script=12'(可选)。
export function plNavigate(id, opts = {}) {
  const { replace = false, search = '' } = opts;
  const url = plPageToPath(id) + (search || '');
  if (__routerNavigate) {
    __routerNavigate(url, { replace });
  } else {
    try { history[replace ? 'replaceState' : 'pushState'](null, '', url); } catch (_) {}
  }
  try { window.dispatchEvent(new CustomEvent('pl-navigate', { detail: id })); } catch (_) {}
}

// 跨区导航(/login、/console、/platform/...):走 React Router 触发懒加载切块。
export function appNavigate(path, opts = {}) {
  const { replace = false } = opts;
  if (__routerNavigate) {
    __routerNavigate(path, { replace });
    return;
  }
  try {
    if (replace) location.replace(path);
    else location.assign(path);
  } catch (_) { location.href = path; }
}

// 整页导航:登出 / 会话过期等需要彻底清空运行时(React state、在途 SSE)的场景。
export function plHardNavigate(path) {
  location.href = path;
}
