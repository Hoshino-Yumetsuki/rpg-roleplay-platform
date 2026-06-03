// Platform 路由块 — 由 main.jsx 懒加载,挂载于 /platform/*。
// 共享基础设施(web-vitals / api-client / a11y / i18n)已由 main.jsx 预加载,此处不重复;
// 仅保留 platform 专属的 side-effect 模块。
import React from 'react';
import { useState, useEffect } from 'react';

// 基础设施 side-effect 模块(设置 window.MOCK_* / SSE bridge 等)
import '../mock-data.js';
// 运行环境采集 — 反馈抽屉提交时附带最近 20 个错误 + 10 个失败 API 给管理员排查
import '../runtime-telemetry.js';
import '../data-loader.js';
import '../state-event-bridge.js';
import '../worldbook-status-toast.js';
import '../ui-atlas.js';
import '../console-assistant-navigation.jsx';

// Cloudscape 设计系统 + 暖色主题(UI 底座)
import '@cloudscape-design/global-styles/index.css';
import { installWarmTheme } from '../cloudscape-theme.js';
installWarmTheme();

// 组件模块 — named import(ESM 自动拉入传递依赖)
import { PlatformShellCS, ProfilePage, MePage, ModulesPage, LibraryPage, UsagePage, CapPage, PL_NAV, AdminGuard,
  AdminUsersPage, AdminGlobalUsagePage, AdminAuditPage, AdminHealthPage,
  AdminLogsPage, AdminRegistrationPage, AdminSecurityPage, AdminMaintenancePage,
  AdminDmcaTakedownsPage, AdminDmcaStrikesPage, AdminCsamReportsPage, AdminAupActionsPage,
  AdminFeedbackPage,
} from '../platform-app.jsx';
import { SavesPage } from '../pages/saves.jsx';
import { ScriptsPage } from '../pages/scripts.jsx';
import { CardsPage } from '../pages/cards.jsx';
import { SettingsPage } from '../pages/settings.jsx';
import { FeedbackPage } from '../pages/feedback.jsx';
import { plPathToPage, plNavigate, plPageToPath, appNavigate } from '../router.js';

// AGE-02: splash gate
import AdultSplash from '../components/AdultSplash.jsx';
const SPLASH_VERSION = 'v1.0-2026-05-31';

// ── 挂载 ──

function ComingSoon({ title, desc }) {
  return (
    <section className="pl-sec">
      <div className="pl-sec-head"><h2>{title}</h2></div>
      <div style={{ padding: '36px 20px', textAlign: 'center' }}>
        <div style={{ fontSize: 26, marginBottom: 10, opacity: 0.7 }}>🚧</div>
        <div style={{ fontSize: 14, color: 'var(--text-quiet)', marginBottom: 6 }}>敬请期待</div>
        <div style={{ fontSize: 13, color: 'var(--muted)' }}>{desc}</div>
      </div>
    </section>
  );
}

const TWEAK_DEFAULTS = {
  startPage: 'profile',
  sidebarWidth: 244,
  accent: 'terracotta',
};

// 合法 page id 全集(History 路由 /<id> 校验用)。settings-deploy 等旧别名在 router.js
// PL_HASH_ALIASES 里归一。
const PL_IDS = [
  ...((PL_NAV || []).filter((i) => i.id).map((i) => i.id)),
  'me', 'me-edit', 'me-settings', 'saves-branches', 'scripts-import', 'cards-npc',
  // 新 IA 子页(Cloudscape 迁移后):剧本 / 开始游戏 / 设置&账户 各模块的左栏子页
  'scripts-library', 'scripts-editor', 'scripts-settings', 'play-settings',
  'settings-models', 'settings-modelparams', 'settings-modules', 'settings-memory',
  'settings-permissions', 'settings-danger', 'admin-deploy',
  'admin-users', 'admin-usage', 'admin-audit', 'admin-health',
  'admin-logs', 'admin-registration', 'admin-security', 'admin-maintenance',
  'admin-dmca-takedowns', 'admin-dmca-strikes', 'admin-csam-reports', 'admin-aup-actions',
  'admin-feedback',
  'usage', 'plugins', 'mcp', 'skills', 'apis', 'feedback',
];
function parsePage() {
  return plPathToPage(PL_IDS);
}

function PlatformApp() {
  const t = TWEAK_DEFAULTS;
  const [page, setPage] = useState(parsePage() || t.startPage || 'profile');
  const [assistantOpen, setAssistantOpen] = useState(false);
  // AGE-02: null = loading, true = need splash, false = no splash needed
  const [splashNeeded, setSplashNeeded] = useState(null);

  useEffect(() => {
    fetch('/api/me/splash/status', { credentials: 'same-origin' })
      .then((r) => r.ok ? r.json() : null)
      .then((j) => { setSplashNeeded(j ? !j.acked : false); })
      .catch(() => { setSplashNeeded(false); });
  }, []);

  useEffect(() => {
    const bus = window.__capBus || (window.__capBus = new EventTarget());
    const onOpen = () => setAssistantOpen(true);
    const onClose = () => setAssistantOpen(false);
    const onToggle = () => setAssistantOpen((v) => !v);
    bus.addEventListener('cap-open', onOpen);
    bus.addEventListener('cap-close', onClose);
    bus.addEventListener('cap-toggle', onToggle);
    return () => {
      bus.removeEventListener('cap-open', onOpen);
      bus.removeEventListener('cap-close', onClose);
      bus.removeEventListener('cap-toggle', onToggle);
    };
  }, []);

  // 首屏:把旧 hash 直达(Platform.html#x)/ 非规范路径规范化成干净路径,保留 query。
  useEffect(() => {
    const canonical = plPageToPath(page) + (location.search || '');
    if (location.pathname + location.search + location.hash !== canonical) {
      try { history.replaceState(null, '', canonical); } catch (_) {}
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 浏览器前进/后退 → 按当前路径重解析;编程跳转(plNavigate)→ pl-navigate 事件。
  useEffect(() => {
    const onPop = () => { const p = parsePage(); if (p) setPage(p); };
    const onNav = (e) => { if (e && e.detail) setPage(e.detail); };
    window.addEventListener('popstate', onPop);
    window.addEventListener('pl-navigate', onNav);
    return () => {
      window.removeEventListener('popstate', onPop);
      window.removeEventListener('pl-navigate', onNav);
    };
  }, []);

  const go = (id) => plNavigate(id);

  let body = null;
  if (page === 'profile') body = <ProfilePage />;
  else if (page === 'me') body = <MePage subPage="overview" />;
  else if (page === 'me-edit') body = <MePage subPage="edit" />;
  else if (page === 'me-settings') body = <MePage subPage="settings" />;
  else if (page === 'scripts') body = <ScriptsPage subPage="list" />;
  else if (page === 'scripts-import') body = <ScriptsPage subPage="import" />;
  else if (page === 'scripts-library') body = <ScriptsPage subPage="library" />;
  // iter#41: scripts-editor / scripts-settings 占位 route 删除 — 兼容旧 hash 重定向到 #scripts list
  else if (page === 'scripts-editor') body = <ScriptsPage subPage="list" />;
  else if (page === 'scripts-settings') body = <ComingSoon title="剧本设置" desc="剧本级设定覆盖(script_overrides)。迁移中。" />;
  else if (page === 'modules') body = <ModulesPage />;
  else if (page === 'saves') body = <SavesPage subPage="list" />;
  else if (page === 'saves-branches') body = <SavesPage subPage="branches" />;
  else if (page === 'play-settings') body = <ComingSoon title="游戏设置" desc="全局游玩默认(元知识/引导/防剧透)。迁移中。" />;
  else if (page === 'library') body = <LibraryPage />;
  else if (page === 'cards') body = <CardsPage subPage="user" />;
  else if (page === 'cards-npc') body = <CardsPage subPage="npc" />;
  else if (page === 'settings') body = <SettingsPage section="preferences" />;
  else if (page === 'settings-models') body = <SettingsPage section="models" />;
  else if (page === 'settings-modelparams') body = <SettingsPage section="modelparams" />;
  else if (page === 'settings-modules') body = <SettingsPage section="modules" />;
  else if (page === 'settings-memory') body = <SettingsPage section="memory" />;
  else if (page === 'settings-permissions') body = <SettingsPage section="permissions" />;
  else if (page === 'settings-danger') body = <SettingsPage section="danger" />;
  else if (page === 'admin-deploy') body = <AdminGuard><SettingsPage section="deploy" /></AdminGuard>;
  else if (page === 'admin-users')        body = <AdminGuard><AdminUsersPage /></AdminGuard>;
  else if (page === 'admin-usage')        body = <AdminGuard><AdminGlobalUsagePage /></AdminGuard>;
  else if (page === 'admin-audit')        body = <AdminGuard><AdminAuditPage /></AdminGuard>;
  else if (page === 'admin-health')       body = <AdminGuard><AdminHealthPage /></AdminGuard>;
  else if (page === 'admin-logs')         body = <AdminGuard><AdminLogsPage /></AdminGuard>;
  else if (page === 'admin-registration') body = <AdminGuard><AdminRegistrationPage /></AdminGuard>;
  else if (page === 'admin-security')     body = <AdminGuard><AdminSecurityPage /></AdminGuard>;
  else if (page === 'admin-maintenance')      body = <AdminGuard><AdminMaintenancePage /></AdminGuard>;
  else if (page === 'admin-dmca-takedowns')   body = <AdminGuard><AdminDmcaTakedownsPage /></AdminGuard>;
  else if (page === 'admin-dmca-strikes')     body = <AdminGuard><AdminDmcaStrikesPage /></AdminGuard>;
  else if (page === 'admin-csam-reports')     body = <AdminGuard><AdminCsamReportsPage /></AdminGuard>;
  else if (page === 'admin-aup-actions')      body = <AdminGuard><AdminAupActionsPage /></AdminGuard>;
  else if (page === 'admin-feedback')         body = <AdminGuard><AdminFeedbackPage /></AdminGuard>;
  else if (page === 'usage') body = <UsagePage />;
  else if (page === 'plugins') body = <CapPage kind="plugins" />;
  else if (page === 'mcp') body = <CapPage kind="mcp" />;
  else if (page === 'skills') body = <CapPage kind="skills" />;
  else if (page === 'apis') body = <CapPage kind="apis" />;
  else if (page === 'feedback') body = <FeedbackPage />;
  else body = <ProfilePage />;

  return (
    <>
      <PlatformShellCS
        page={page}
        setPage={go}
      >
        {body}
      </PlatformShellCS>
      {splashNeeded && (
        <AdultSplash
          splashVersion={SPLASH_VERSION}
          onAcked={() => setSplashNeeded(false)}
        />
      )}
    </>
  );
}

// Platform 路由块导出 — React Router 在 /platform/* 挂载本组件。
export default function PlatformRoute() {
  useEffect(() => {
    // 鉴权 gate(原 __gateThenMount):在线但未登录 → 跳登录,带 next 回跳目标。
    const offline = new URLSearchParams(location.search).has('offline');
    const gate = (info) => {
      if (info && info.online && !info.authed && !offline) {
        const next = encodeURIComponent(location.pathname + location.search + location.hash);
        appNavigate('/login?next=' + next, { replace: true });
      }
    };
    if (window.RPG_DATA_READY) {
      window.RPG_DATA_READY.then(gate).catch(() => {});
    }
  }, []);

  return <PlatformApp />;
}
