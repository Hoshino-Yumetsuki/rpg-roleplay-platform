// @ts-nocheck

// GitHub /login/device 式设备授权页。外部客户端(本地部署/CLI)发起设备码流后,
// 用户在浏览器打开本页,输入/确认配对码,看清请求方 + 权限 + 防钓鱼提示后批准。
// 未登录时由平台 auth gate 引导登录再回跳本页(/device)。
import React from 'react';
import { useState as useStatePL, useEffect as useEffectPL } from 'react';
import CSContainer from '@cloudscape-design/components/container';
import CSHeader from '@cloudscape-design/components/header';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSBox from '@cloudscape-design/components/box';
import CSButton from '@cloudscape-design/components/button';
import CSInput from '@cloudscape-design/components/input';
import CSAlert from '@cloudscape-design/components/alert';
import CSBadge from '@cloudscape-design/components/badge';

const SCOPE_LABEL = { 'library:read': '浏览并导入在线剧本库', 'library:publish': '把剧本发布到在线库' };

export function DeviceAuthorizePage() {
  const initialCode = (() => {
    try { return (new URLSearchParams(location.search).get('code') || '').toUpperCase(); } catch { return ''; }
  })();
  const [code, setCode] = useStatePL(initialCode);
  const [info, setInfo] = useStatePL(null);          // {client_name, scopes}
  const [phase, setPhase] = useStatePL('input');      // input | confirm | done | denied | error
  const [busy, setBusy] = useStatePL(false);
  const [err, setErr] = useStatePL('');
  const [provider, setProvider] = useStatePL(null);   // null=loading, true/false

  useEffectPL(() => {
    window.api?.federation?.providerInfo?.()
      .then((r) => setProvider(!!r?.provider_enabled))
      .catch(() => setProvider(false));
  }, []);

  const lookup = async (c) => {
    const uc = (c || code).trim().toUpperCase();
    if (!uc) return;
    setBusy(true); setErr('');
    try {
      const r = await window.api.federation.deviceLookup(uc);
      setInfo(r.device); setPhase('confirm');
    } catch (e) {
      setErr(e?.payload?.error || '配对码不存在或已过期'); setPhase('error');
    } finally { setBusy(false); }
  };

  useEffectPL(() => { if (initialCode) lookup(initialCode); /* eslint-disable-next-line */ }, []);

  const decide = async (deny) => {
    setBusy(true); setErr('');
    try {
      await window.api.federation.deviceApprove(code.trim().toUpperCase(), deny);
      setPhase(deny ? 'denied' : 'done');
    } catch (e) {
      setErr(e?.payload?.error || '操作失败'); setPhase('error');
    } finally { setBusy(false); }
  };

  return (
    <div style={{ maxWidth: 520, margin: '48px auto', padding: '0 16px' }}>
      <CSContainer header={<CSHeader variant="h1">授权设备接入</CSHeader>}>
        <CSSpaceBetween size="l">
          {provider === false && (
            <CSAlert type="info" header="此实例不是在线剧本库提供方">
              本实例是本地/自部署节点,不签发设备授权。设备配对码只能在你要连接的「在线服务」上输入。
              若你是想连接官方在线库,请在「设置 → 在线剧本库」里发起连接。
            </CSAlert>
          )}
          {provider !== false && phase === 'input' && (
            <CSSpaceBetween size="s">
              <CSBox color="text-body-secondary">
                在你的设备/本地部署上发起连接后会显示一个配对码,请在此输入以授权。
              </CSBox>
              <div style={{ display: 'flex', gap: 8 }}>
                <div style={{ flex: 1 }}>
                  <CSInput value={code} placeholder="WXYZ-7K9M" autoFocus
                    onChange={({ detail }) => setCode(detail.value.toUpperCase())}
                    onKeyDown={(e) => { if (e.detail.key === 'Enter') lookup(); }} />
                </div>
                <CSButton variant="primary" loading={busy} disabled={!code.trim()} onClick={() => lookup()}>下一步</CSButton>
              </div>
            </CSSpaceBetween>
          )}

          {phase === 'confirm' && info && (
            <CSSpaceBetween size="m">
              <CSBox variant="awsui-key-label">配对码</CSBox>
              <CSBox fontSize="display-l" fontWeight="bold" padding="n" style={{ letterSpacing: 3 }}>{code.toUpperCase()}</CSBox>

              <div>
                <CSBox variant="awsui-key-label">请求方</CSBox>
                <CSBox>{info.client_name || '未命名客户端'}</CSBox>
              </div>
              <div>
                <CSBox variant="awsui-key-label">申请权限</CSBox>
                <CSSpaceBetween direction="horizontal" size="xs">
                  {(info.scopes || []).map((s) => <CSBadge key={s} color="blue">{SCOPE_LABEL[s] || s}</CSBadge>)}
                </CSSpaceBetween>
              </div>

              <CSAlert type="warning" header="确认这是你本人发起的连接">
                只有当你正在自己的设备/本地部署上主动连接时才批准。如果你没有发起此请求,
                或配对码来自他人发来的链接/消息,请点「拒绝」—— 批准会把以上权限授予对方。
              </CSAlert>

              <CSSpaceBetween direction="horizontal" size="xs">
                <CSButton variant="primary" loading={busy} onClick={() => decide(false)}>批准授权</CSButton>
                <CSButton loading={busy} onClick={() => decide(true)}>拒绝</CSButton>
              </CSSpaceBetween>
            </CSSpaceBetween>
          )}

          {phase === 'done' && (
            <CSAlert type="success" header="已授权">
              你的设备会在几秒内自动完成连接,可以回到它继续操作了。本页可关闭。
            </CSAlert>
          )}
          {phase === 'denied' && (
            <CSAlert type="info" header="已拒绝">该连接请求已被拒绝,未授予任何权限。</CSAlert>
          )}
          {phase === 'error' && (
            <CSSpaceBetween size="s">
              <CSAlert type="error" header="无法继续">{err}</CSAlert>
              <CSButton onClick={() => { setPhase('input'); setInfo(null); setErr(''); }}>重新输入配对码</CSButton>
            </CSSpaceBetween>
          )}
        </CSSpaceBetween>
      </CSContainer>
    </div>
  );
}

export default DeviceAuthorizePage;
