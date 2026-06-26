# H · 多端适配设计方案 v1（手机端深度定制）

> 状态：**已定向（2026-06-03 决策锁定）**。本文档是「根据前端实际情况整理的设计方案」，不是实施记录。
> 目标：手机端**全新设计**而非桌面响应式缩水；触摸优先；信息密度合理；**收敛弹窗**。
> 适用范围：`frontend/` 全站（React + Vite + Cloudscape）。

---

## 0. TL;DR（先看这个）

项目其实是**两个性质完全不同的前端表面**，必须分开对待，不能用同一套响应式规则硬套：

| 表面 | 文件 | 性质 | 桌面美学 | 手机现状 |
|---|---|---|---|---|
| **游玩面**（Play） | `game-app.jsx` + `game-console.css` | 沉浸式叙事聊天 | 仿 Claude 网页：780px 居中阅读栏 | **~70% 已做**：汉堡抽屉 + 底部 Sheet（`@media ≤768px`） |
| **管理面**（Manage） | `platform-app.jsx` + 10 个 `pages/*` | 数据密集：表格/表单/向导 | 仿 AWS 控制台 Cloudscape 暖色 | **导航壳已收（AppLayout 自带抽屉），内容页 0 适配** |

方案的三条主线：
1. **游玩面**：从「能用」打磨到「像一个高级的中文互动小说阅读器」——阅读排版、输入条、状态 Sheet 三处精修。
2. **管理面**：换上**原生移动壳**——底部 Tab 栏一级导航 + 卡片化列表 + 全屏流程，**消灭层叠弹窗**。
3. **抽出一套移动原语组件库**（BottomSheet / TabBar / ActionSheet / FullScreenFlow / MobileList），两个表面共用，避免在 4000 行大文件里散落 `@media`。

---

## 1. 现状诊断（事实，全部带证据）

### 1.1 断点系统：齐备但几乎没人用
- `responsive.jsx` 定义了完整断点：`xs<480 / sm 480–767 / md 768–1023 / lg 1024–1279 / xl≥1280`，导出 `useBreakpoint()`（返回 `is.ltMd` 等便捷布尔）、`useResizable()`（已支持触摸拖拽）、`ResizeHandle`、`chatComposerKey`（已处理 IME/Enter 发送）。
- **但 `useBreakpoint` 全站只有 `game-app.jsx` 一处 import**。10 个管理页**零** `useBreakpoint`、零页面级 `@media`。
- 结论：**基建有，落地几乎没有**。这是好事——我们不必造轮子，直接用这套断点做单一开关。

### 1.2 游玩面（game-app）：移动架构已成型
`game-console.css` 已有针对性移动处理（非缩水）：
- `≤768px`（L1461–1584）：左栏 → `position:fixed` 汉堡抽屉（`min(300px,86vw)`，backdrop 点击关闭）；右侧游戏面板 → 底部 Sheet（`height:88vh`、18px 圆角、抓手、40px 触摸 pill 标签、`-webkit-overflow-scrolling:touch`）；浮动按钮 `.gc-float-panel-btn` 唤起。
- `≤760px`（L795）：模型选择器只留图标。`≤720px`（L969/1585）：命令菜单单列、聊天栏收窄。
- `pointer:coarse`（L57/1162）：拖拽手柄加宽到 12px 命中区。
- **缺口**：阅读排版未为窄屏重设计（行高/字号/段距仍沿用桌面）；输入条未做安全区与移动键盘避让；Sheet 没有手势下滑关闭；顶栏信息在窄屏偏挤。

### 1.3 管理面（platform-app + pages）：壳收了，肉没收
- 外壳是 Cloudscape `AppLayout`（L4259），带 `navigationOpen/onNavigationChange`——**Cloudscape 在窄屏自动把 SideNavigation 收成汉堡抽屉**。所以「导航」层不是 0 适配。
- **真正的缺口在内容页**：`admin / cards / saves / scripts / settings / new-game-wizard / script-edit-* ` 全是桌面表格 + 多列表单 + 层叠 Modal，窄屏直接溢出/挤压。
- `platform.css`（2070 行）有 10 个 `@media`，但集中在**平板档**（980/820/720/640），是零散补丁，不是手机重设计。

### 1.4 弹窗密度：与「不允许过多弹窗」直接冲突
| 页面 | Modal/Drawer 量级 |
|---|---|
| `admin.jsx` | **~151**（用户管理/日志/注册/安全/维护/DMCA/CSAM/AUP 各种确认框） |
| `scripts.jsx` | ~30（发布/版本史/导入/删除） |
| `saves.jsx` | ~20（新建/删除/分支） |
| `settings.jsx` | ~18 |
| `cards.jsx` | 6 |

桌面层叠弹窗在手机上是体验灾难（占满屏、嵌套、误触遮罩丢数据）。**这是本次改造最大的结构性工作量**。

### 1.5 全局移动基础：地基不错，差「安全区」临门一脚
- ✅ 三入口都有 `viewport meta`；`platform.css` 有 `-webkit-text-size-adjust`、`touch-action:manipulation`、`tap-highlight:transparent`、`≤767px input ≥16px`（防 iOS 聚焦缩放）。
- ❌ **viewport 缺 `viewport-fit=cover`**（`Platform.html` / `Login.html` / `Game Console.html` 第 5 行均无），**全站无 `env(safe-area-inset-*)`** → 刘海屏/灵动岛/底部 Home 横条会压内容、Tab 栏与输入条会被系统手势条吃掉。**这是地基级必修项。**

### 1.6 组件库：没有任何移动专用原语
`components/` 下是业务组件（ModelPicker/FeedbackDrawer/…），**没有 BottomSheet / MobileTabBar / ActionSheet / FullScreenFlow** 这类原语。当前所有「弹层」都是 Cloudscape `CSModal`，在手机上不可控。

---

## 2. 设计取向（Design Direction）

> 一句话：**让游玩面像「掌中的卷轴」，让管理面像「一个体面的原生 App」。** 两者共享暖色调与字体系统，但交互模型分治。

### 2.1 游玩面 —— 「掌中卷轴」(Scroll-in-Palm)
互动小说/网文的阅读体验是核心资产，手机上要把它做成**一流的沉浸式阅读器**：
- **阅读栏**：边到边但留呼吸边距（16–20px），GM 叙事用更大的行高（1.7–1.8）与略偏书卷感的字阶；系统/工具消息弱化为次级层。
- **输入条**：底部常驻，贴安全区，软键盘弹出时主区上推而非被遮；`chatComposerKey` 已就绪（Enter 发送 / Shift+Enter 换行 / IME 安全）。
- **游戏状态**：库存/时间线/角色卡/分支留在**底部 Sheet**，抓手可见、支持**下滑手势关闭**、半展/全展两档。
- **氛围**：保留暖色与现有质感，避免炫技；阅读场景克制优先。

### 2.2 管理面 —— 原生 App 壳
- **底部 Tab 栏**做一级导航（4–5 个高频入口 + 「更多」溢出 Sheet），替代「汉堡抽屉藏一切」。拇指可达、信息架构外显。
- **层叠弹窗 → 两种原生模式**：
  - **快速操作/选择/确认** → **BottomSheet / ActionSheet**（不离开当前上下文）。
  - **多步/长表单**（新建游戏向导、导入、剧本编辑） → **全屏流程**（FullScreenFlow，带顶部返回/进度，路由级而非弹层）。
- **表格 → 卡片列表**：`saves/scripts/cards/admin` 的表格在窄屏转为可点按的堆叠卡片，关键信息分层展示。
- **信息密度**：每屏聚焦一件事；次级信息折叠进「详情」二级页或 Sheet。

### 2.3 视觉系统沿用，不另起炉灶
继续用现有暖色主题 + 现有字体栈，**不引入第二套视觉语言**，避免双端割裂与维护成本。移动端是「同一套设计语言的原生化表达」，不是换皮。

---

## 3. 技术架构

### 3.1 单一开关：`useIsMobile()`
- 基于已有 `useBreakpoint().is.ltMd`（<768px）封装 `useIsMobile()`，作为**全站唯一**的「是否移动壳」判断；必要处再用 `is.ltSm`（<480）做极窄微调。
- **原则：按「表现层分支」而非「CSS 挤压」**。共享数据/状态/业务逻辑，只在**外壳层 + 重内容页**按 `isMobile` 渲染不同的展示组件。**不 fork 4000 行大文件**——抽出移动壳包裹 + 列表/表格条件渲染。

### 3.2 移动原语组件库（新增 `components/mobile/`）
一次造好、两表面复用：

| 组件 | 职责 | 替代 |
|---|---|---|
| `BottomSheet` | 半屏/全屏 Sheet，抓手，下滑关闭，safe-area，焦点陷阱 | 大量 `CSModal` |
| `ActionSheet` | 底部动作列表（确认/选择/危险操作） | 小确认 Modal |
| `MobileTabBar` | 底部一级导航 + 溢出「更多」 | 汉堡藏一切 |
| `MobilePageHeader` | 返回 + 标题 + 右动作，sticky | Cloudscape Header 在窄屏 |
| `FullScreenFlow` | 全屏多步流程（顶部进度/返回/关闭） | 向导/导入的层叠 Modal |
| `MobileList` / `MobileCard` | 表格 → 卡片列表 | `CSTable` 窄屏 |

全部内建 `env(safe-area-inset-*)`、44px+ 触摸目标、`prefers-reduced-motion` 兜底。

### 3.3 地基修复（P0，先做）
1. 三入口 viewport 改 `width=device-width, initial-scale=1, viewport-fit=cover`。
2. 全局 safe-area token：`--safe-top/right/bottom/left: env(safe-area-inset-*)`，Tab 栏/输入条/Sheet 统一吃这套。
3. 移动 token 补齐（触摸目标尺寸、移动专用间距阶、移动字阶）落 `tokens.css`。

### 3.4 弹窗治理映射表（指导原则）
| 原弹窗类型 | 手机替代 |
|---|---|
| 危险确认（删除/重置） | `ActionSheet`（红色主操作，底部，易撤销位置） |
| 单项选择（选模型/选存档/选剧本） | `BottomSheet` 列表 |
| 表单编辑（角色卡/设置项） | 全屏二级页 或 高 Sheet |
| 多步向导（新建游戏/导入） | `FullScreenFlow` |
| 纯信息提示 | inline `Alert` / toast，不弹层 |

---

## 4. 分阶段实施计划

> 每阶段独立可交付、可在真机验证后再进下一阶段。

### P0 · 地基与原语（无 UI 可见变更，但是一切的前提）
- viewport `viewport-fit=cover` ×3、safe-area token、移动 token。
- `useIsMobile()`。
- 移动原语库首批：`BottomSheet`、`ActionSheet`、`MobilePageHeader`、`MobileTabBar`（骨架）。
- 真机验证：刘海屏不压内容、Sheet 手势、键盘避让。

### P1 · 双外壳移动化（骨架先立起来）
- **管理壳**：接入 `MobileTabBar`（一级导航），窄屏隐藏/弱化 Cloudscape 汉堡，页头换 `MobilePageHeader`。
- **游玩壳**：把现有 `≤768px` 抽屉/Sheet 重构到新原语之上，补阅读排版 + 输入条安全区 + Sheet 下滑关闭。

### P2 · 高频管理页卡片化（saves / scripts / cards）
- 列表表格 → `MobileList`/`MobileCard`。
- 这三页的 Modal（~56 个）按§3.4 映射改造为 Sheet/ActionSheet/全屏流。

### P3 · 长表单与向导（new-game-wizard / settings / 导入流）
- 向导/导入 → `FullScreenFlow`（多步、进度、可中断恢复）。
- settings → 分组二级页（按模块分配模型等重区单独成页）。

### P4 · 长尾全量移动化（admin / script-edit-*）【决策：全量】
- `admin.jsx`（~151 弹窗）：所有管理弹窗按§3.4 全量改 Sheet/ActionSheet/全屏流；用户管理/审计/日志等表格全部卡片化；危险操作（封号/删除/CSAM 处置）用 `ActionSheet` 红色主操作 + 二次确认。
- 剧本编辑器（`script-edit-canon` / `script-edit-worldbook` / `script-modules-panel`）：inline 表格编辑 → 移动卡片 + 全屏编辑流；世界书树形结构在窄屏用可折叠层级列表。
- 因范围拉满，P4 自身需再拆子阶段（P4a admin 列表/弹窗、P4b 剧本编辑器、P4c 世界书树），逐个真机验证。

---

## 5. 决策（已锁定 2026-06-03）

1. **一级导航模型** → ✅ **底部 Tab 栏**（拇指可达、IA 外显，原生 App 手感）。
2. **弹窗哲学** → ✅ **全面改 Sheet + 全屏流**（快确认→ActionSheet，选择→BottomSheet，多步→FullScreenFlow；纯提示→inline/toast）。
3. **admin/剧本编辑器范围** → ✅ **全量移动化**（不设「建议桌面」围栏；~151 admin 弹窗 + 编辑器全部移动化，见 P4 子阶段）。
4. **视觉语言** → ✅ **沿用暖色 + 现有字体栈做原生化**（同一设计语言的原生表达，双端一致、单轨维护）。

> 方向锁定。下一步：按 P0→P4 推进，每阶段在真机验证后再进下一阶段；P4 因全量化再拆 P4a/b/c。

---

## 附 · 关键文件索引
- 断点/拖拽：`frontend/src/responsive.jsx`
- 游玩壳：`frontend/src/game-app.jsx` · 样式 `frontend/src/game-console.css`（移动块 L1461–1594）
- 管理壳：`frontend/src/platform-app.jsx`（AppLayout L4259，导航 getPLNav L59）
- 全局样式：`frontend/src/platform.css`（移动 @media L27 起）· token `frontend/src/tokens.css`
- 入口 HTML（viewport）：`frontend/Platform.html` · `frontend/Login.html` · `frontend/Game Console.html`（均第 5 行）
- 弹窗重灾：`pages/admin.jsx` · `pages/scripts.jsx` · `pages/saves.jsx` · `pages/settings.jsx`
