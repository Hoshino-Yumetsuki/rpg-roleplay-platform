import React from 'react';
import CSModal from '@cloudscape-design/components/modal';
import CSBox from '@cloudscape-design/components/box';
import CSSpaceBetween from '@cloudscape-design/components/space-between';
import CSButton from '@cloudscape-design/components/button';
import CSFormField from '@cloudscape-design/components/form-field';
import CSTextarea from '@cloudscape-design/components/textarea';
import CSAlert from '@cloudscape-design/components/alert';
import CSStatusIndicator from '@cloudscape-design/components/status-indicator';
import AgentModelPicker from './AgentModelPicker.jsx';
import ImageSizePicker from './ImageSizePicker.jsx';

/* GenerateImageModal — AI 生图弹窗，复用 CSModal + AgentModelPicker 范式。

   props:
     open           : boolean  是否可见
     onClose        : ()=>void  关闭回调
     kind           : 生图类型 'cover'|'avatar'|'card'|'chat'|'game'|'persona'
     attach         : { type, id } 可选，生成后写入目标
     defaultPrompt  : 默认 prompt 文本
     onDone         : (url:string)=>void  生成成功并获得 URL 后回调

   内部流程:
     1. 点「生成」→ POST /api/images/generate → {image_id, status:'pending'}
     2. 每 2s 轮询 GET /api/images/{image_id} 直到 status==='done' 或 'failed'
     3. done → onDone(url) + 关闭弹窗
     4. failed / credentials_required → 显示错误提示
*/
export default function GenerateImageModal({
  open,
  onClose,
  kind = 'avatar',
  attach,
  defaultPrompt = '',
  onDone,
  saveId,
}) {
  const { useState, useEffect, useRef } = React;

  const [prompt, setPrompt] = useState(defaultPrompt);
  const [size, setSize] = useState('');
  const [selModel, setSelModel] = useState({ api_id: '', model: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [credsMissing, setCredsMissing] = useState(false);
  const pollTimer = useRef(null);

  // 当 defaultPrompt 变化(如父组件切换上下文)时同步
  useEffect(() => {
    setPrompt(defaultPrompt);
  }, [defaultPrompt]);

  // 弹窗关闭时清理轮询
  useEffect(() => {
    if (!open) {
      if (pollTimer.current) {
        clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
    }
  }, [open]);

  function stopPoll() {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }

  async function pollStatus(imageId) {
    stopPoll();
    try {
      const res = await window.api.images.get(imageId);
      if (!res) {
        setBusy(false);
        setError('轮询返回空响应');
        return;
      }
      const status = res.status;
      if (status === 'done') {
        setBusy(false);
        if (onDone) onDone(res.url);
        if (onClose) onClose();
        return;
      }
      if (status === 'failed') {
        setBusy(false);
        const errMsg = res.error || '生成失败';
        const isCredsMissing = typeof errMsg === 'string'
          && (errMsg.includes('credentials_required') || errMsg.includes('needs_credentials'));
        if (isCredsMissing) {
          setCredsMissing(true);
          setError('请先在设置中配置该 Provider 的 API Key，再重试。');
        } else {
          setCredsMissing(false);
          setError(errMsg);
        }
        return;
      }
      // pending / generating → 继续轮询
      pollTimer.current = setTimeout(() => pollStatus(imageId), 2000);
    } catch (e) {
      setBusy(false);
      setError((e && e.message) || '轮询出错');
    }
  }

  async function handleGenerate() {
    const trimmedPrompt = (prompt || '').trim();
    if (!trimmedPrompt) {
      setError('请填写生成描述（Prompt）');
      return;
    }
    if (!selModel.api_id || !selModel.model) {
      setError('请先选择模型');
      return;
    }
    setError(null);
    setCredsMissing(false);
    setBusy(true);
    try {
      const body = {
        prompt: trimmedPrompt,
        kind,
        api_id: selModel.api_id,
        model: selModel.model,
      };
      if (attach) body.attach = attach;
      if (saveId != null) body.save_id = saveId;
      if (size) body.size = size;
      const res = await window.api.images.generate(body);
      if (!res || !res.image_id) {
        setBusy(false);
        setError('服务端未返回任务 ID');
        return;
      }
      // 开始轮询
      pollStatus(res.image_id);
    } catch (e) {
      setBusy(false);
      const errMsg = (e && e.message) || '请求失败';
      const payload = e && e.payload;
      const detail = (payload && (payload.detail || payload.error)) || errMsg;
      const isCredsMissing = typeof detail === 'string'
        && (detail.includes('credentials_required') || detail.includes('needs_credentials'));
      if (isCredsMissing) {
        setCredsMissing(true);
        setError('请先在设置中配置该 Provider 的 API Key，再重试。');
      } else {
        setCredsMissing(false);
        setError(detail);
      }
    }
  }

  function handleClose() {
    if (busy) return;
    stopPoll();
    setError(null);
    setCredsMissing(false);
    if (onClose) onClose();
  }

  return (
    <CSModal
      visible={!!open}
      onDismiss={handleClose}
      header="AI 生图"
      footer={
        <CSBox float="right">
          <CSSpaceBetween direction="horizontal" size="xs">
            <CSButton onClick={handleClose} disabled={busy}>取消</CSButton>
            <CSButton
              variant="primary"
              loading={busy}
              disabled={busy || !(prompt || '').trim()}
              onClick={handleGenerate}
            >
              生成
            </CSButton>
          </CSSpaceBetween>
        </CSBox>
      }
    >
      <CSSpaceBetween size="m">
        {busy && (
          <CSStatusIndicator type="loading">
            生成中，请稍候…
          </CSStatusIndicator>
        )}
        {error && (
          <CSAlert
            type="error"
            header={credsMissing ? '缺少 API Key' : '生成失败'}
            action={credsMissing
              ? <CSButton iconName="settings" onClick={() => { window.location.hash = 'settings-models'; }}>去配 Key</CSButton>
              : undefined
            }
          >
            {error}
          </CSAlert>
        )}
        <CSFormField
          label="生成描述（Prompt）"
          description="描述你想生成的图片内容，越具体越好。"
        >
          <CSTextarea
            value={prompt}
            onChange={({ detail }) => setPrompt(detail.value)}
            placeholder="例如：身着白色汉服的年轻女子，清澈眼神，水墨风格"
            rows={3}
            disabled={busy}
          />
        </CSFormField>
        <AgentModelPicker
          prefPrefix="image_gen"
          fallbackPrefix="gm"
          capabilityFilter="image_gen"
          variant="bare"
          header={undefined}
          description="选择生图模型（仅展示支持图像生成的模型）"
          configHash="settings-models"
          onChange={(api_id, model) => setSelModel({ api_id, model })}
        />
        <CSFormField label="尺寸 / 比例" description="按用途推荐默认比例；改一次后本地记住。vertex(Gemini) 暂不支持自定义尺寸">
          <ImageSizePicker kind={kind} value={size} onChange={setSize} />
        </CSFormField>
      </CSSpaceBetween>
    </CSModal>
  );
}
