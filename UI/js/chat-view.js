const VIEW_SESSION_KEY = 'dnd-active-session';

function sessionKey(session) {
  if (!session || !session.type) return '';
  if (session.type === 'consult') return 'consult';
  if (session.type === 'save') return `save:${session.id || ''}`;
  return '';
}

function sameSession(a, b) {
  return sessionKey(a) === sessionKey(b);
}

function persistViewSession(session) {
  if (!session) {
    sessionStorage.removeItem(VIEW_SESSION_KEY);
    return;
  }
  sessionStorage.setItem(VIEW_SESSION_KEY, JSON.stringify(session));
}

function readPersistedViewSession() {
  try {
    const raw = sessionStorage.getItem(VIEW_SESSION_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function clearPersistedViewSession() {
  sessionStorage.removeItem(VIEW_SESSION_KEY);
}

function chatUiText(key) {
  const en = String(getChatLanguage()).toLowerCase().startsWith('en');
  if (key === 'reasoning') {
    return en ? 'Thinking' : '思考过程';
  }
  if (key === 'placeholder') {
    return en
      ? 'Type a message. Enter to send, Shift+Enter for a new line'
      : '输入消息，Enter 发送，Shift+Enter 换行';
  }
  if (key === 'sendTip') {
    return en ? 'Send' : '发送';
  }
  if (key === 'saveTip') {
    return en
      ? 'Create a copy of the current game'
      : '创建当前游戏副本';
  }
  return '';
}

function applyChatInputPlaceholder() {
  const input = document.querySelector('#view-body .chat-input');
  if (input) input.placeholder = chatUiText('placeholder');

  const sendBtn = document.getElementById('btn-chat-send');
  if (sendBtn) {
    const tip = chatUiText('sendTip');
    sendBtn.setAttribute('aria-label', tip);
    const tipEl = sendBtn.querySelector('.chat-input-btn-tip');
    if (tipEl) tipEl.textContent = tip;
  }

  const saveBtn = document.getElementById('btn-chat-save');
  if (saveBtn) {
    const tip = chatUiText('saveTip');
    saveBtn.setAttribute('aria-label', tip);
    const tipEl = saveBtn.querySelector('.chat-input-btn-tip');
    if (tipEl) tipEl.textContent = tip;
  }
}

function syncChatSaveButton() {
  const saveBtn = document.getElementById('btn-chat-save');
  if (!saveBtn) return;
  saveBtn.hidden = window.activeSession?.type === 'consult';
}

function syncChatSendEnabled() {
  const allowSend = window.activeSession?.type === 'consult';
  const sendBtn = document.getElementById('btn-chat-send');
  if (sendBtn) sendBtn.disabled = !allowSend || chatSendBusy;
  const input = document.querySelector('#view-body .chat-input');
  if (input) input.readOnly = !allowSend;
}

function ensureChatShell() {
  const body = document.getElementById('view-body');
  if (!body) return null;
  if (body.querySelector('.chat-root')) {
    return body.querySelector('.chat-root');
  }

  body.innerHTML = `
    <div class="chat-root">
      <div class="chat-stage">
        <div class="chat-messages-scroll">
          <div class="chat-column">
            <div class="chat-messages"></div>
          </div>
        </div>
      </div>
      <div class="chat-input-area">
        <div class="chat-column">
          <div class="chat-input-shell">
            <textarea class="chat-input" rows="4" placeholder=""></textarea>
            <div class="chat-input-toolbar">
              <button type="button" class="chat-input-btn chat-input-btn-save" id="btn-chat-save" aria-label="Save">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                  <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
                  <polyline points="17 21 17 13 7 13 7 21"/>
                  <polyline points="7 3 7 8 15 8"/>
                </svg>
                <span class="chat-input-btn-tip"></span>
              </button>
              <button type="button" class="chat-input-btn chat-input-btn-send" id="btn-chat-send" aria-label="Send">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">
                  <path d="M12 19V5"/>
                  <path d="M5 12l7-7 7 7"/>
                </svg>
                <span class="chat-input-btn-tip"></span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;
  bindChatScrollTracking();
  return body.querySelector('.chat-root');
}

function syncChatViewTitle() {
    if (window.activeView !== 'chat' || !window.activeSession) return;
    const title = document.getElementById('view-title');
    if (title) title.textContent = chatTitleForSession(window.activeSession);
  }

function chatTitleForSession(session) {
    if (!session) return '';
    if (session.type === 'consult') {
      const label = document.querySelector('#btn-consult .nav-label');
      return label?.textContent?.trim() || '';
    }
    if (session.type === 'save') return session.title || session.id || '';
    return '';
  }

  function openChatSession(session, options = {}) {
    if (!session || !session.type) return;
  
    const force = options.force === true;
    if (
      !force &&
      window.activeView === 'chat' &&
      sameSession(window.activeSession, session)
    ) {
      return;
    }
  
    window.activeView = 'chat';
    window.activeSession = session;
    persistViewSession(session);
  
    const title = document.getElementById('view-title');
    if (title) title.textContent = chatTitleForSession(session);
  
    ensureChatShell();
    bindChatInput();
    applyChatInputPlaceholder();
    syncChatSaveButton();
    syncChatSendEnabled();
  
    const messages = document.querySelector('#view-body .chat-messages');
    if (messages) messages.innerHTML = '';
  
    if (session.type === 'consult') {
      loadConsultMessages();
    } else if (session.type === 'save' && session.id) {
      loadGameMessages(session.id);
    }
  }

function restoreViewFromSession() {
  const session = readPersistedViewSession();
  if (!session || !session.type) return false;
  if (session.type === 'save' && !session.id) return false;
  openChatSession(session, { force: true });
  return true;
}

document.getElementById('btn-consult').addEventListener('click', () => {
  openChatSession({ type: 'consult' });
});

function getChatScrollEl() {
  return document.querySelector('#view-body .chat-messages-scroll');
}

let chatStickToBottom = true;
let chatScrollRaf = 0;
let chatScrollBound = false;

function isChatNearBottom(threshold = 16) {
  const el = getChatScrollEl();
  if (!el) return true;
  return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}

function bindChatScrollTracking() {
  const el = getChatScrollEl();
  if (!el || chatScrollBound) return;
  chatScrollBound = true;
  el.addEventListener('scroll', () => {
    chatStickToBottom = isChatNearBottom(16);
  }, { passive: true });
}

function scrollChatToBottom() {
  const el = getChatScrollEl();
  if (!el) return;
  el.scrollTop = el.scrollHeight;
  chatStickToBottom = true;
}

function scrollChatToBottomIfNeeded() {
  if (!chatStickToBottom) return;
  if (chatScrollRaf) return;
  chatScrollRaf = requestAnimationFrame(() => {
    chatScrollRaf = 0;
    if (!chatStickToBottom) return;
    scrollChatToBottom();
  });
}

function getChatLanguage() {
  if (window.activeSession?.language) {
    return window.activeSession.language;
  }
  return window.AppState?.settings?.language || 'zh-CN';
}

function showThinkingIndicator(label) {
  const box = document.querySelector('#view-body .chat-messages');
  if (!box) return null;
  hideThinkingIndicator();

  const row = document.createElement('div');
  row.className = 'chat-message chat-message-dm chat-message-thinking';
  row.dataset.thinking = 'true';

  const avatar = document.createElement('div');
  avatar.className = 'chat-avatar';
  avatar.textContent = label || 'DM';

  const thinking = document.createElement('div');
  thinking.className = 'chat-thinking';
  thinking.setAttribute('role', 'status');
  thinking.setAttribute('aria-label', 'Thinking');
  for (let i = 0; i < 3; i += 1) {
    const dot = document.createElement('div');
    dot.className = 'chat-thinking-dot';
    thinking.appendChild(dot);
  }

  row.appendChild(avatar);
  row.appendChild(thinking);
  box.appendChild(row);
  scrollChatToBottom();
  return row;
}

function hideThinkingIndicator() {
  const box = document.querySelector('#view-body .chat-messages');
  if (!box) return;
  const existing = box.querySelector('[data-thinking="true"]');
  if (existing) existing.remove();
}

function createCopyButton(text) {
  const actions = document.createElement('div');
  actions.className = 'chat-message-actions';

  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'chat-copy-btn';
  btn.setAttribute('aria-label', 'Copy');
  btn.innerHTML = `
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
    </svg>
  `;

  btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    try {
      await navigator.clipboard.writeText(text);
      btn.classList.add('copied');
      btn.setAttribute('aria-label', 'Copied');
      setTimeout(() => {
        btn.classList.remove('copied');
        btn.setAttribute('aria-label', 'Copy');
      }, 1500);
    } catch (_) {}
  });

  actions.appendChild(btn);
  return actions;
}

function appendMessage(container, role, text, label, options = {}) {
  const row = document.createElement('div');
  row.className = 'chat-message chat-message-' + role;

  const avatar = document.createElement('div');
  avatar.className = 'chat-avatar';
  avatar.textContent = label || (role === 'dm' ? 'DM' : 'A');

  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';

  const content = document.createElement('div');
  if (role === 'dm') {
    content.className = 'chat-text chat-text-md md-content';
    content.innerHTML = typeof renderMarkdown === 'function'
      ? renderMarkdown(text)
      : (text || '');
  } else {
    content.className = 'chat-text';
    content.textContent = text || '';
  }
  bubble.appendChild(content);

  const body = document.createElement('div');
  body.className = 'chat-message-body';

  if (role === 'dm' && options.reasoning) {
    const reasoning = createReasoningBlock();
    reasoning.textEl.textContent = options.reasoning;
    reasoning.block.hidden = false;
    body.appendChild(reasoning.block);
  }

  body.appendChild(bubble);
  body.appendChild(createCopyButton(text || ''));

  if (role === 'dm') {
    row.appendChild(avatar);
    row.appendChild(body);
  } else {
    row.appendChild(body);
    row.appendChild(avatar);
  }

  container.appendChild(row);
}

function renderChatMessages(list) {
  const box = document.querySelector('#view-body .chat-messages');
  if (!box) return;
  box.innerHTML = '';
  const playerLabel = (window.AppState?.account || 'A').charAt(0).toUpperCase();
  (list || []).forEach(msg => {
    const role = msg.role === 'user' || msg.role === 'player' ? 'player' : 'dm';
    const text = msg.content || msg.text || '';
    appendMessage(box, role, text, role === 'dm' ? 'DM' : playerLabel, {
      reasoning: msg.reasoning || '',
    });
  });
  scrollChatToBottom();
}

function appendChatMessage(role, content) {
  const box = document.querySelector('#view-body .chat-messages');
  if (!box) return;
  const uiRole = role === 'user' || role === 'player' ? 'player' : 'dm';
  const label = uiRole === 'dm'
    ? 'DM'
    : (window.AppState?.account || 'A').charAt(0).toUpperCase();
  appendMessage(box, uiRole, content, label);
  scrollChatToBottom();
}

function createReasoningBlock() {
  const block = document.createElement('div');
  block.className = 'chat-reasoning';

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'chat-reasoning-toggle expanded';
  toggle.setAttribute('aria-expanded', 'true');
  toggle.innerHTML = `
    <span class="chat-reasoning-chevron" aria-hidden="true">▸</span>
    <span>${chatUiText('reasoning')}</span>
  `;

  const panel = document.createElement('div');
  panel.className = 'chat-reasoning-panel';
  panel.hidden = false;

  const text = document.createElement('div');
  text.className = 'chat-reasoning-text';
  panel.appendChild(text);

  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', expanded ? 'false' : 'true');
    panel.hidden = expanded;
    toggle.classList.toggle('expanded', !expanded);
  });

  block.appendChild(toggle);
  block.appendChild(panel);
  return { block, textEl: text };
}

function beginStreamingDmMessage() {
  const box = document.querySelector('#view-body .chat-messages');
  if (!box) return null;

  const row = document.createElement('div');
  row.className = 'chat-message chat-message-dm';

  const avatar = document.createElement('div');
  avatar.className = 'chat-avatar';
  avatar.textContent = 'DM';

  const body = document.createElement('div');
  body.className = 'chat-message-body';

  const reasoning = createReasoningBlock();
  reasoning.block.hidden = true;

  const bubble = document.createElement('div');
  bubble.className = 'chat-bubble';
  bubble.hidden = true;

  const content = document.createElement('div');
  content.className = 'chat-text chat-text-md md-content';
  bubble.appendChild(content);

  body.appendChild(reasoning.block);
  body.appendChild(bubble);

  const actionsHost = document.createElement('div');
  body.appendChild(actionsHost);

  row.appendChild(avatar);
  row.appendChild(body);

  let streamUiReady = false;

  return {
    contentEl: content,
    bubbleEl: bubble,
    reasoningBlock: reasoning.block,
    reasoningTextEl: reasoning.textEl,
    actionsHost,
    ensureStreamUi() {
      if (streamUiReady) return;
      streamUiReady = true;
      hideThinkingIndicator();
      box.appendChild(row);
    },
    setContentVisible(visible) {
      bubble.hidden = !visible;
      if (visible) {
        bubble.style.display = '';
      } else {
        bubble.style.display = 'none';
      }
    },
    setCopyText(finalText) {
      actionsHost.innerHTML = '';
      if (finalText) {
        actionsHost.appendChild(createCopyButton(finalText));
      }
    },
  };
}

let chatSendBusy = false;

function setChatSendBusy(busy) {
  chatSendBusy = busy;
  syncChatSendEnabled();
}

async function sendChatMessage() {
  const input = document.querySelector('#view-body .chat-input');
  if (!input || chatSendBusy) return;
  if (window.activeSession?.type !== 'consult') return;
  const text = input.value.trim();
  if (!text) return;

  chatStickToBottom = true;
  appendChatMessage('player', text);
  input.value = '';
  input.style.height = '';
  setChatSendBusy(true);

  const dm = beginStreamingDmMessage();
  showThinkingIndicator('DM');
  let contentAcc = '';
  let thinkingAcc = '';

  try {
    const res = await fetch('api/consult/message/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.error || String(res.status));
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop() || '';

      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data:')) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        const ev = JSON.parse(payload);

        if (ev.type === 'thinking') {
          dm.ensureStreamUi();
          thinkingAcc += ev.delta || '';
          dm.reasoningBlock.hidden = false;
          dm.reasoningTextEl.textContent = thinkingAcc;
          scrollChatToBottomIfNeeded();
        } else if (ev.type === 'content') {
          dm.ensureStreamUi();
          contentAcc += ev.delta || '';
          dm.setContentVisible(true);
          dm.contentEl.innerHTML = typeof renderMarkdown === 'function'
            ? renderMarkdown(contentAcc)
            : contentAcc;
          scrollChatToBottomIfNeeded();
        } else if (ev.type === 'done') {
          dm.ensureStreamUi();
          const finalText = ev.content || contentAcc;
          if (finalText) {
            dm.setContentVisible(true);
            dm.contentEl.innerHTML = typeof renderMarkdown === 'function'
              ? renderMarkdown(finalText)
              : finalText;
            dm.setCopyText(finalText);
          } else {
            dm.setContentVisible(false);
            dm.setCopyText('');
          }
          if (ev.thinking || thinkingAcc) {
            dm.reasoningBlock.hidden = false;
            dm.reasoningTextEl.textContent = ev.thinking || thinkingAcc;
          }
          scrollChatToBottomIfNeeded();
        } else if (ev.type === 'error') {
          throw new Error(ev.error || 'stream error');
        }
      }
    }
  } catch (err) {
    hideThinkingIndicator();
    if (dm) {
      dm.ensureStreamUi();
      dm.setContentVisible(true);
      dm.contentEl.textContent = String(err.message || err);
    } else {
      appendChatMessage('dm', String(err.message || err));
    }
  } finally {
    hideThinkingIndicator();
    setChatSendBusy(false);
    input.focus();
  }
}

function bindChatInput() {
  const input = document.querySelector('#view-body .chat-input');
  if (!input || input.dataset.bound === '1') return;
  input.dataset.bound = '1';

  input.addEventListener('keydown', e => {
    if (e.key !== 'Enter' || e.shiftKey) return;
    e.preventDefault();
    sendChatMessage();
  });

  const sendBtn = document.getElementById('btn-chat-send');
  if (sendBtn) {
    sendBtn.addEventListener('click', () => {
      sendChatMessage();
    });
  }

  const saveBtn = document.getElementById('btn-chat-save');
  if (saveBtn) {
    saveBtn.addEventListener('click', async () => {
      if (window.activeSession?.type !== 'save' || !window.activeSession.id) return;
      if (typeof duplicateSave !== 'function') return;
      try {
        await duplicateSave(window.activeSession.id);
      } catch (err) {
        window.alert(String(err.message || err));
      }
    });
  }
}

async function loadConsultMessages() {
  const res = await fetch('api/consult/messages');
  if (!res.ok) return;
  const data = await res.json();
  if (window.activeSession && data.language) {
    window.activeSession.language = data.language;
    persistViewSession(window.activeSession);
  }
  applyChatInputPlaceholder();
  renderChatMessages(data.messages || []);
}

async function loadGameMessages(saveId) {
  const res = await fetch('api/game/messages?id=' + encodeURIComponent(saveId));
  if (!res.ok) return;
  const data = await res.json();
  renderChatMessages(data.messages || []);
}

function openClearConsultModal() {
  const modal = document.getElementById('clear-consult-modal');
  if (modal) modal.classList.remove('hidden');
}

function closeClearConsultModal() {
  const modal = document.getElementById('clear-consult-modal');
  if (modal) modal.classList.add('hidden');
}

async function confirmClearConsult() {
  try {
    const res = await fetch('api/consult/clear', { method: 'POST' });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.error || String(res.status));
    }
    location.reload();
  } catch (err) {
    closeClearConsultModal();
    window.alert(String(err.message || err));
  }
}

(function bindClearConsultUi() {
  const clearBtn = document.getElementById('btn-consult-clear');
  if (clearBtn) {
    clearBtn.addEventListener('click', e => {
      e.stopPropagation();
      openClearConsultModal();
    });
  }

  const cancelBtn = document.getElementById('btn-cancel-clear-consult');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', () => {
      closeClearConsultModal();
    });
  }

  const confirmBtn = document.getElementById('btn-confirm-clear-consult');
  if (confirmBtn) {
    confirmBtn.addEventListener('click', () => {
      confirmClearConsult();
    });
  }

  const modal = document.getElementById('clear-consult-modal');
  if (modal) {
    modal.addEventListener('click', e => {
      if (e.target === modal) closeClearConsultModal();
    });
  }
})();

