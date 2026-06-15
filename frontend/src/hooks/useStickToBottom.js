/* useStickToBottom — Claude 风「自动跟随到底 + 用户上滚即停 + 回到底部按钮」收口。
 *
 * 此前四处聊天流(桌面游戏 game-app.ChatArea / 桌面酒馆 tavern-app.TavernChatArea /
 * 手机游戏 MobileGame / 手机酒馆 MobileTavern.ChatView)各自手抄一份相同的滚动守卫,
 * 阈值/策略逐字重复。本 hook 把那段逐字提炼成单一实现 —— 行为零变化:
 *
 *   ① onScroll:距底 < 80px 算「在底部」(threshold=80,逐字保留);
 *   ② 跟随策略(deps 变化时触发):
 *        · 首屏(hasContent && 首次)→ 强制到底;
 *        · 末条是玩家(lastIsUser)→ 强制到底;
 *        · 否则双守卫:用户已上滚(atBottom=false) 或 实时距底 > 360px → 不跟随
 *          (GM 输出含 running→false 时不把正在看上文的用户硬拽回底部)。
 *   ③ 可选「回到最新」按钮态(withButton):onScroll 离开底部即显示,跳底后隐藏。
 *
 * 各宿主差异用参数保留:
 *   - mode 'instant'(桌面游戏/桌面酒馆/手机酒馆):rAF 内 scrollTop = scrollHeight,
 *     并 cancelAnimationFrame 清理(逐字保留原写法)。
 *   - mode 'smooth'(手机游戏):rAF 内 scrollTo({behavior:'smooth'}),无 rAF 清理
 *     (逐字保留 MobileGame.scrollBottom(true))。
 *   - withButton(桌面游戏/桌面酒馆/手机酒馆显示按钮;手机游戏无按钮 → false)。
 *   - scrollOnMount(手机游戏挂载即 scrollBottom(false) 用 'auto')。
 *   - deps:跟随 effect 的依赖数组。桌面游戏用 [visible.length, running, rawSteps?.length],
 *     其余用 [history.length, running]。调用方按原 deps 逐字传入。
 *   - lastIsUser / hasContent:调用方按【完整】history 计算后传入(桌面游戏窗口化渲染时,
 *     首屏门控用 visible.length>0,而「末条玩家」判定仍读完整 history —— 由调用方负责,
 *     与原代码一致)。
 */
import { useRef, useState, useEffect } from 'react';

export function useStickToBottom(scrollRef, opts = {}) {
  const {
    deps = [],
    lastIsUser = false,
    hasContent = false,
    mode = 'instant',          // 'instant' | 'smooth'
    withButton = true,
    scrollOnMount = false,
  } = opts;

  const atBottomRef = useRef(true);
  const isFirstLoadRef = useRef(true);
  const [showJump, setShowJump] = useState(false);

  // 跟随 effect 的依赖随调用方传入(逐字保留各宿主原 deps);非响应式参数走 ref 读最新值,
  // 避免把它们塞进 deps 改变触发时机。
  const followRef = useRef({ lastIsUser, hasContent, mode });
  followRef.current = { lastIsUser, hasContent, mode };

  // ① onScroll:记录是否在底部(threshold=80)。withButton 时同步「回到最新」按钮态。
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      atBottomRef.current = atBottom;
      if (withButton) setShowJump(!atBottom);
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 手机游戏:挂载即滚底('auto',逐字保留 scrollBottom(false))。
  useEffect(() => {
    if (!scrollOnMount) return;
    const el = scrollRef.current;
    if (!el) return;
    requestAnimationFrame(() => el.scrollTo({ top: el.scrollHeight, behavior: 'auto' }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ② 跟随策略:首屏/末条玩家 → 强制到底;否则双守卫。
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const { lastIsUser: lu, hasContent: hc, mode: md } = followRef.current;
    if (hc && isFirstLoadRef.current) {
      isFirstLoadRef.current = false;
      atBottomRef.current = true;
    } else if (lu) {
      atBottomRef.current = true;  // 自己发的:跟到底
    } else if (!atBottomRef.current || (el.scrollHeight - el.scrollTop - el.clientHeight) > 360) {
      return;  // 用户在看上文 → 不强制跟随
    }
    if (md === 'smooth') {
      // 手机游戏:scrollTo smooth,无 rAF 清理(逐字保留原 scrollBottom(true))。
      requestAnimationFrame(() => {
        const e2 = scrollRef.current;
        if (e2) e2.scrollTo({ top: e2.scrollHeight, behavior: 'smooth' });
      });
      return;
    }
    // 桌面游戏/桌面酒馆/手机酒馆:直接 scrollTop,带 rAF 清理。
    const id = requestAnimationFrame(() => {
      if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    });
    return () => cancelAnimationFrame(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  // ③ 「回到最新」点击:smooth 跳底 + 复位状态(逐字保留各宿主 onClick 内核)。
  const jumpToBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    atBottomRef.current = true;
    if (withButton) setShowJump(false);
  };

  return { showJump, jumpToBottom, atBottomRef, isFirstLoadRef };
}

export default useStickToBottom;
