// router.js —— Platform 单页应用的轻量 History 路由(取代 hash 路由)。
//
// 设计:
//   · 干净 URL:page id `settings` ↔ 路径 `/settings`;首页 `profile` ↔ `/`。
//   · plNavigate(id) = pushState + 派发 `pl-navigate` 事件;PlatformApp 同时监听
//     popstate(浏览器前进/后退)与 pl-navigate(任意组件编程跳转)→ 统一更新 page。
//   · 兼容旧链接:命中 `Platform.html#x` / 残留 hash 时,从 hash 抢救 page id,
//     首屏 replaceState 规范化成干净路径(老书签/外链不破)。
//   · query(?script=…)按需透传:plNavigate 默认丢弃旧 query,需要时显式传 search。
//
// 后端必须为这些路径做 history-fallback(返回 Platform.html),否则深链/刷新 404。

export const PL_HASH_ALIASES = { branches: 'saves-branches', 'settings-deploy': 'admin-deploy' };

// page id → 路径。
// 注意:主页用 /profile 而非裸 /。生产 Cloudflare 有「裸 / → /Login.html」上游规则,
// 若 SPA 落到 / 会被 CF 弹回登录页(登录后跳 / 会死循环)。用 /profile 绕开。
export function plPageToPath(id) {
  return '/' + (id || 'profile');
}

// 当前 URL → page id(无效返回 null;空/根/入口文件名 → 'profile')
export function plPathToPage(validIds) {
  let raw = '';
  try { raw = decodeURIComponent((location.pathname || '/').replace(/^\/+/, '').replace(/\/+$/, '')); }
  catch (_) { raw = (location.pathname || '/').replace(/^\/+/, '').replace(/\/+$/, ''); }
  // 旧 Platform.html#x 直达 / 残留 hash → 从 hash 抢救
  if ((!raw || raw === 'Platform.html' || raw === 'index.html') && location.hash) {
    raw = location.hash.replace(/^#/, '').split('?')[0];
  }
  raw = PL_HASH_ALIASES[raw] || raw;
  if (!raw || raw === 'Platform.html' || raw === 'index.html') return 'profile';
  if (validIds && !validIds.includes(raw)) return null;
  return raw;
}

// 编程跳转:写 URL + 通知 PlatformApp。search 形如 '?script=12'(可选)。
export function plNavigate(id, opts = {}) {
  const { replace = false, search = '' } = opts;
  const url = plPageToPath(id) + (search || '');
  try { history[replace ? 'replaceState' : 'pushState'](null, '', url); } catch (_) {}
  try { window.dispatchEvent(new CustomEvent('pl-navigate', { detail: id })); } catch (_) {}
}

// 跨文档跳转(进入 Game Console 等独立文档时用):整页导航到干净路径。
export function plHardNavigate(path) {
  location.href = path;
}
