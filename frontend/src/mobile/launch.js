/* launch.js — 移动端进入游戏台。
   桌面 __openContinue 会开新标签;移动端改为同标签全屏跳转(无弹窗拦截、贴合手机)。
   P2 上线后会被"页内移动游戏台 overlay"取代。 */
export async function launchSave(save, nodeId) {
  const id = (save && typeof save === 'object') ? save.id : save;
  if (!id) { try { window.__apiToast?.('没有可进入的存档', { kind: 'warn', duration: 2200 }); } catch (_) {} return; }
  try {
    if (nodeId != null && nodeId !== '') {
      await window.api.branches.activate({ node_id: nodeId, commit_id: nodeId });
    } else {
      await window.api.saves.activate(id);
    }
  } catch (e) {
    try { window.__apiToast?.('切换存档失败', { kind: 'danger', detail: e?.message, duration: 3000 }); } catch (_) {}
    return;
  }
  try { window.location.href = new URL('Game Console.html', window.location.href).href; }
  catch (_) { window.location.href = 'Game Console.html'; }
}
