async function showTemplatesView() {
  window.activeView = 'templates';
  if (typeof syncTopBarNotesButton === 'function') {
    syncTopBarNotesButton();
  }
  window.activeSession = null;
  if (typeof clearPersistedViewSession === 'function') {
    clearPersistedViewSession();
  }
  if (typeof clearSidebarSaveActive === 'function') {
    clearSidebarSaveActive();
  }

  const title = document.getElementById('view-title');
  const body = document.getElementById('view-body');
  if (title) {
    title.textContent = typeof t === 'function' ? t('templates') : '现有模板';
  }
  if (!body) return;

  body.innerHTML = `
    <div class="templates-view">
      <p class="templates-hint" id="templates-hint"></p>
      <div class="templates-list" id="templates-list"></div>
    </div>
  `;
  const hint = document.getElementById('templates-hint');
  if (hint) {
    hint.textContent = typeof t === 'function' ? t('templatesHint') : '选择一个模板，将复制为你的游戏存档。';
  }

  const list = document.getElementById('templates-list');
  if (!list) return;

  try {
    const res = await fetch('api/templates/game', { cache: 'no-store' });
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    const templates = Array.isArray(data.templates) ? data.templates : [];
    if (!templates.length) {
      list.innerHTML = `<p class="templates-empty">${
        typeof t === 'function' ? t('templatesEmpty') : '暂无可用模板'
      }</p>`;
      return;
    }

    templates.forEach(item => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'templates-item-btn';
      btn.textContent = item.title || item.id;
      btn.dataset.id = item.id;
      btn.addEventListener('click', () => createSaveFromTemplate(item.id, btn));
      list.appendChild(btn);
    });
  } catch (err) {
    list.innerHTML = `<p class="templates-empty">${String(err.message || err)}</p>`;
  }
}

async function createSaveFromTemplate(templateId, btn) {
  if (!templateId) return;
  if (btn) btn.disabled = true;
  try {
    const res = await fetch('api/templates/game/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: templateId }),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.error || String(res.status));
    }
    const data = await res.json();
    if (Array.isArray(data.data) && typeof metaCache !== 'undefined') {
      metaCache = data.data;
      if (typeof renderSaveList === 'function') {
        renderSaveList();
      }
    } else if (typeof loadSavesList === 'function') {
      await loadSavesList();
    } else if (typeof renderSaveList === 'function') {
      renderSaveList();
    }
    if (btn) btn.disabled = false;
  } catch (err) {
    window.alert(String(err.message || err));
    if (btn) btn.disabled = false;
  }
}

(function bindTemplatesNav() {
  const btn = document.getElementById('btn-templates');
  if (!btn || btn.dataset.bound === '1') return;
  btn.dataset.bound = '1';
  btn.addEventListener('click', () => {
    showTemplatesView();
  });
})();
