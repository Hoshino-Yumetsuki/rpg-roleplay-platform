// Login 路由块 — 由 main.jsx 懒加载,挂载于 /login。
// 共享基础设施(web-vitals / api-client / a11y / i18n)已由 main.jsx 预加载,此处不重复。
import React from 'react';
import { LoginApp } from './LoginApp';

export default function LoginRoute() {
  return <LoginApp />;
}
