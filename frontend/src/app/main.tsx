// @ts-nocheck
// main.jsx — 全站唯一 ESM 入口。
// 单 index.html + React Router:按路径懒加载 login / platform / console 三个路由块。
// 取代原先 Login.html / Platform.html / Game Console.html 各自的 createRoot 入口。
import '../lib/web-vitals-rum';
import React, { Suspense, lazy, useEffect } from 'react';
import * as ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';

// 全站共享基础设施(三区都用):API 客户端 / i18n / a11y 镜像。
import '../lib/api-client';
import '../lib/a11y-tooltip-labels';
import '../i18n/index';

import { ErrorBoundary } from '../components/ErrorBoundary';
import { setRouterNavigate } from './router';

// 区级懒加载:login / platform / console 各自独立 chunk(含各自的 side-effect 模块)。
const LoginRoute = lazy(() => import('../features/auth/LoginEntry'));
const PlatformRoute = lazy(() => import('../features/platform/PlatformEntry'));
const ConsoleRoute = lazy(() => import('../features/console/ConsoleEntry'));

// React Router 的 navigate 注入 router.js,使非组件代码(plNavigate/appNavigate)可触发切区。
function NavigationBridge() {
  const navigate = useNavigate();
  useEffect(() => {
    setRouterNavigate(navigate);
    return () => setRouterNavigate(null);
  }, [navigate]);
  return null;
}

function Splash() {
  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg, #121110)',
        color: 'var(--text, #c8c2b7)',
      }}
    >
      <div
        style={{
          width: 38,
          height: 38,
          border: '3px solid rgba(201,100,66,.25)',
          borderTopColor: 'var(--accent, #c96442)',
          borderRadius: '50%',
          animation: 'app-spin .85s linear infinite',
        }}
      />
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
      <NavigationBridge />
      <Suspense fallback={<Splash />}>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route path="/platform/*" element={<PlatformRoute />} />
          <Route path="/console" element={<ConsoleRoute />} />
          {/* 默认入口:platform 工作台(原 Platform.html 是事实上的首页)。 */}
          <Route path="/" element={<Navigate to="/platform/" replace />} />
          <Route path="*" element={<Navigate to="/platform/" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>,
);

// HTML splash 淡出 + 移除
try {
  document.body.classList.add('app-mounted');
  setTimeout(() => {
    const sp = document.getElementById('app-splash');
    if (sp && sp.parentNode) sp.parentNode.removeChild(sp);
  }, 300);
} catch (_) {}
