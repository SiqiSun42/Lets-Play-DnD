let historyState = {
  oldestId: null,
  hasMore: false,
  loading: false,
  expandedIds: new Set(),
  mode: 'exact',
  appliedQuery: '',
};

function isConsultNotesMode() {
  return window.activeSession?.type === 'consult';
}

function getHistorySearchQuery() {
  if (historyState.mode !== 'exact') return '';
  return historyState.appliedQuery;
}

function historyApiUrl(beforeId) {
  let base = '';
  if (window.activeSession?.type === 'consult') {
    base = 'api/consult/history';
  } else if (window.activeSession?.type === 'save' && window.activeSession.id) {
    base = `api/game/history?id=${encodeURIComponent(window.activeSession.id)}`;
  } else {
    return null;
  }
  const params = new URLSearchParams();
  if (beforeId != null) params.set('before_id', String(beforeId));
  const q = getHistorySearchQuery();
  if (q) params.set('q', q);
  const qs = params.toString();
  return qs ? `${base}?${qs}` : base;
}

function historyPlayerLabel() {
  return typeof getAccountAvatarLetter === 'function' ? getAccountAvatarLetter() : 'A';
}

function historyMessageRole(msg) {
  return msg.role === 'user' || msg.role === 'player' ? 'player' : 'dm';
}

function historyAvatarLabel(role) {
  return role === 'player' ? historyPlayerLabel() : 'DM';
}

function historyItemHtml(msg) {
  const role = historyMessageRole(msg);
  const label = historyAvatarLabel(role);
  const expanded = historyState.expandedIds.has(msg.id);
  const text = msg.content || '';
  const bodyHtml = typeof renderMarkdown === 'function' ? renderMarkdown(text) : text;
  return `
    <div class="notes-history-item${expanded ? ' is-expanded' : ''}" data-history-id="${msg.id}" role="button" tabindex="0">
      <div class="notes-history-avatar notes-history-avatar--${role}">${label}</div>
      <div class="notes-history-content md-content${expanded ? '' : ' is-collapsed'}">${bodyHtml}</div>
    </div>
  `;
}

function syncHistoryItemAlign(el) {
  const content = el.querySelector('.notes-history-content');
  if (!content || el.classList.contains('is-expanded')) {
    el.classList.remove('is-single-line');
    return;
  }
  const lineHeight = parseFloat(getComputedStyle(content).lineHeight) || 21;
  const single = content.scrollHeight <= lineHeight + 1;
  el.classList.toggle('is-single-line', single);
}

function syncAllHistoryItemsAlign() {
  document.querySelectorAll('.notes-history-item').forEach(syncHistoryItemAlign);
}

function bindHistoryItem(el) {
  const toggle = () => {
    const id = Number(el.dataset.historyId);
    if (!id) return;
    if (historyState.expandedIds.has(id)) {
      historyState.expandedIds.delete(id);
    } else {
      historyState.expandedIds.add(id);
    }
    el.classList.toggle('is-expanded');
    el.querySelector('.notes-history-content')?.classList.toggle('is-collapsed');
    syncHistoryItemAlign(el);
  };
  el.addEventListener('click', toggle);
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      toggle();
    }
  });
  syncHistoryItemAlign(el);
}

function appendHistoryMessages(list) {
  const container = document.getElementById('notes-history-items');
  if (!container || !list?.length) return;
  const frag = document.createDocumentFragment();
  list.forEach(msg => {
    const wrap = document.createElement('div');
    wrap.innerHTML = historyItemHtml(msg);
    const item = wrap.firstElementChild;
    if (item) {
      bindHistoryItem(item);
      frag.appendChild(item);
    }
  });
  container.appendChild(frag);
}

function renderHistoryMessages(list) {
  const container = document.getElementById('notes-history-items');
  if (!container) return;
  container.innerHTML = '';
  if (!list?.length) {
    const emptyKey = getHistorySearchQuery() ? 'notesHistoryNoResults' : 'notesHistoryEmpty';
    container.innerHTML = `<p class="notes-empty">${t(emptyKey)}</p>`;
    return;
  }
  appendHistoryMessages(list);
}

async function fetchHistoryPage(beforeId) {
  const url = historyApiUrl(beforeId);
  if (!url) return { messages: [], has_more: false };
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) return { messages: [], has_more: false };
  return res.json().catch(() => ({ messages: [], has_more: false }));
}

async function loadHistoryInitial() {
  historyState.oldestId = null;
  historyState.hasMore = false;
  historyState.loading = false;
  const data = await fetchHistoryPage(null);
  const list = data.messages || [];
  historyState.hasMore = !!data.has_more;
  if (list.length) {
    historyState.oldestId = list[list.length - 1].id;
  }
  return list;
}

async function loadMoreHistory() {
  if (!historyState.hasMore || historyState.loading || historyState.oldestId == null) return;
  historyState.loading = true;
  try {
    const data = await fetchHistoryPage(historyState.oldestId);
    const list = data.messages || [];
    if (list.length) {
      appendHistoryMessages(list);
      historyState.oldestId = list[list.length - 1].id;
    }
    historyState.hasMore = !!data.has_more;
  } finally {
    historyState.loading = false;
  }
}

async function reloadHistoryList() {
  historyState.expandedIds.clear();
  const list = await loadHistoryInitial();
  renderHistoryMessages(list);
}

function runHistorySearch() {
  if (historyState.mode !== 'exact') return;
  const input = document.getElementById('notes-history-search');
  historyState.appliedQuery = (input?.value || '').trim();
  reloadHistoryList();
}

function bindHistoryScroll() {
  const el = document.getElementById('notes-history-scroll');
  if (!el || el.dataset.historyScrollBound === '1') return;
  el.dataset.historyScrollBound = '1';
  el.addEventListener('scroll', () => {
    if (notesState.section !== 'history') return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= 48;
    if (nearBottom) loadMoreHistory();
  }, { passive: true });
}

function bindHistoryToolbar() {
  const btn = document.getElementById('notes-history-mode-btn');
  const menu = document.getElementById('notes-history-mode-menu');
  const input = document.getElementById('notes-history-search');
  const queryBtn = document.getElementById('notes-history-query-btn');
  if (!btn || !menu) return;

  const syncToolbarDisabled = () => {
    const disabled = historyState.mode !== 'exact';
    if (input) input.disabled = disabled;
    if (queryBtn) queryBtn.disabled = disabled;
  };

  btn.onclick = e => {
    e.stopPropagation();
    menu.classList.toggle('hidden');
  };

  menu.onclick = e => {
    const option = e.target.closest('button[data-mode]');
    if (!option) return;
    historyState.mode = option.dataset.mode || 'exact';
    btn.textContent = option.textContent;
    menu.querySelectorAll('button').forEach(b => b.classList.toggle('active', b === option));
    menu.classList.add('hidden');
    if (historyState.mode !== 'exact') {
      historyState.appliedQuery = '';
    }
    syncToolbarDisabled();
    reloadHistoryList();
  };

  if (queryBtn) {
    queryBtn.onclick = () => runHistorySearch();
  }

  if (input) {
    syncToolbarDisabled();
    input.onkeydown = e => {
      if (e.key === 'Enter' && historyState.mode === 'exact') {
        e.preventDefault();
        runHistorySearch();
      }
    };
  }

  if (document.body.dataset.historyToolbarDocBound !== '1') {
    document.body.dataset.historyToolbarDocBound = '1';
    document.addEventListener('click', e => {
      const modeMenu = document.getElementById('notes-history-mode-menu');
      const modeBtn = document.getElementById('notes-history-mode-btn');
      if (!modeMenu || !modeBtn || modeMenu.classList.contains('hidden')) return;
      if (!modeMenu.contains(e.target) && e.target !== modeBtn) {
        modeMenu.classList.add('hidden');
      }
    });
  }
}

function historyPageShell(bodyHtml) {
  return `
    <div class="notes-page notes-history-page">
      <div class="notes-page-header">
        <h2 class="notes-page-title">${t('notesHistory')}</h2>
        <div class="notes-page-divider"></div>
      </div>
      <div class="notes-history-toolbar">
        <input type="text" class="notes-history-search" id="notes-history-search" placeholder="${t('notesHistorySearch')}" autocomplete="off">
        <button type="button" class="notes-history-query-btn" id="notes-history-query-btn">${t('notesHistoryQuery')}</button>
        <div class="notes-history-mode-picker">
          <button type="button" class="notes-history-mode-btn" id="notes-history-mode-btn">${t('notesHistoryExact')}</button>
          <div class="notes-history-mode-menu hidden" id="notes-history-mode-menu">
            <button type="button" class="active" data-mode="exact">${t('notesHistoryExact')}</button>
            <button type="button" data-mode="smart">${t('notesHistorySmart')}</button>
          </div>
        </div>
      </div>
      <div class="notes-page-body notes-history-scroll" id="notes-history-scroll">
        <div class="notes-history-list" id="notes-history-items">${bodyHtml || ''}</div>
      </div>
    </div>
  `;
}

async function renderHistoryPanel(panel) {
  if (!historyApiUrl(null)) {
    panel.innerHTML = `<p class="notes-empty">${t('notesNoSave')}</p>`;
    return;
  }

  panel.innerHTML = historyPageShell('');
  bindHistoryToolbar();
  bindHistoryScroll();

  const list = await loadHistoryInitial();
  renderHistoryMessages(list);
}

function resetHistoryPanel() {
  historyState.oldestId = null;
  historyState.hasMore = false;
  historyState.loading = false;
  historyState.mode = 'exact';
  historyState.appliedQuery = '';
  historyState.expandedIds.clear();
  const scroll = document.getElementById('notes-history-scroll');
  if (scroll) {
    scroll.dataset.historyScrollBound = '';
  }
}
