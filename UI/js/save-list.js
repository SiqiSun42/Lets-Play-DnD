let metaCache = [];
let sidebarActiveSaveId = null;
let menuTargetSaveId = null;
let deleteTargetSaveId = null;
let renameTargetSaveId = null;

function isGameSave(item) {
  return item && item.id && item.id !== 'consult';
}

function lastPlayedMs(item) {
  if (!item || !item.last_played) return 0;
  const t = Date.parse(item.last_played);
  return Number.isFinite(t) ? t : 0;
}

function sortGameSaves(list) {
  return [...list].sort((a, b) => {
    if (!!a.pinned !== !!b.pinned) return a.pinned ? -1 : 1;
    return lastPlayedMs(b) - lastPlayedMs(a);
  });
}

function filteredGameSaves() {
  const input = document.getElementById('save-search');
  const q = (input?.value || '').trim().toLowerCase();
  const games = sortGameSaves(metaCache.filter(isGameSave));
  if (!q) return games;
  return games.filter(s => String(s.title || '').toLowerCase().includes(q));
}

async function fetchMeta() {
  const res = await fetch('/api/meta');
  if (!res.ok) return;
  const data = await res.json();
  metaCache = Array.isArray(data.meta) ? data.meta : [];
}

async function patchSaveMeta(saveId, patch) {
  const res = await fetch('/api/meta/patch-by-id', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: saveId, patch }),
  });
  if (!res.ok) {
    const errBody = await res.json().catch(() => ({}));
    throw new Error(errBody.error || String(res.status));
  }
  const data = await res.json();
  if (Array.isArray(data.data)) {
    metaCache = data.data;
  } else {
    const item = metaCache.find(s => s.id === saveId);
    if (item) Object.assign(item, patch);
  }
}

function nowIso() {
  return new Date().toISOString();
}

function closeSaveMenu() {
  const menu = document.getElementById('save-menu');
  if (menu) menu.classList.add('hidden');
  menuTargetSaveId = null;
}

function positionSaveMenu(menu, rect) {
    menu.classList.remove('hidden');
    const menuRect = menu.getBoundingClientRect();
    let top = rect.top - menuRect.height - 4;
    let left = rect.left;
    if (left + menuRect.width > window.innerWidth) {
      left = window.innerWidth - menuRect.width - 8;
    }
    if (top < 8) {
      top = 8;
    }
    menu.style.top = top + 'px';
    menu.style.left = left + 'px';
  }

function openSaveMenu(e, saveId) {
  e.stopPropagation();
  closeSaveMenu();
  menuTargetSaveId = saveId;
  const save = metaCache.find(s => s.id === saveId);
  const menu = document.getElementById('save-menu');
  if (!menu || !save) return;

  const pinBtn = menu.querySelector('[data-action="pin"]');
  if (pinBtn) {
    const label = pinBtn.querySelector('span:not(.menu-icon)');
    const en = String(window.AppState?.settings?.language || 'zh-CN').toLowerCase().startsWith('en');
    if (label) {
      label.textContent = save.pinned
        ? (en ? 'Unpin' : '取消固定')
        : (typeof t === 'function' ? t('pin') : (en ? 'Pin' : '固定'));
    }
  }

  positionSaveMenu(menu, e.currentTarget.getBoundingClientRect());
}

function clearSidebarSaveActive() {
  sidebarActiveSaveId = null;
  renderSaveList();
}

function renderSaveList() {
  const saveList = document.getElementById('save-list');
  if (!saveList) return;
  saveList.innerHTML = '';

  filteredGameSaves().forEach(save => {
    const li = document.createElement('li');
    li.className = 'save-item'
      + (save.pinned ? ' pinned' : '')
      + (save.id === sidebarActiveSaveId ? ' active' : '');
    li.dataset.id = save.id;

    const row = document.createElement('div');
    row.className = 'save-item-row';

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'save-item-btn';

    if (save.pinned) {
      const pin = document.createElement('span');
      pin.className = 'pin-icon';
      pin.textContent = '📌';
      btn.appendChild(pin);
    }

    const nameSpan = document.createElement('span');
    nameSpan.className = 'save-name';
    nameSpan.textContent = save.title || save.id;
    btn.appendChild(nameSpan);

    btn.addEventListener('click', async () => {
        sidebarActiveSaveId = save.id;
        try {
            await patchSaveMeta(save.id, { last_played: nowIso() });
        } catch (_) {}
        renderSaveList();
        
        if (typeof openChatSession === 'function') {
            openChatSession({
            type: 'save',
            id: save.id,
            title: save.title || save.id,
            language: save.in_game_language || 'zh-CN',
            });
        }
    });

    const menuBtn = document.createElement('button');
    menuBtn.type = 'button';
    menuBtn.className = 'save-menu-btn';
    menuBtn.textContent = '⋮';
    menuBtn.setAttribute(
      'aria-label',
      typeof t === 'function' ? t('saveOptions') || 'Save options' : 'Save options'
    );
    menuBtn.addEventListener('click', e => openSaveMenu(e, save.id));

    row.appendChild(btn);
    row.appendChild(menuBtn);
    li.appendChild(row);
    saveList.appendChild(li);
  });
}

async function duplicateSave(sourceId) {
    if (!sourceId || sourceId === 'consult') return null;
    const res = await fetch('/api/meta/duplicate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: sourceId }),
    });
    if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.error || String(res.status));
    }
    const data = await res.json();
    if (Array.isArray(data.data)) {
        metaCache = data.data;
    }
    renderSaveList();
    return data.new || null;
}

function openDeleteSaveModal(saveId) {
    deleteTargetSaveId = saveId;
    const modal = document.getElementById('delete-modal');
    if (modal) modal.classList.remove('hidden');
}
  
function closeDeleteSaveModal() {
    deleteTargetSaveId = null;
    const modal = document.getElementById('delete-modal');
    if (modal) modal.classList.add('hidden');
}
  
async function confirmDeleteSave() {
    const saveId = deleteTargetSaveId;
    if (!saveId) return;
    try {
      const res = await fetch('/api/meta/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: saveId }),
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.error || String(res.status));
      }
      const data = await res.json();
      if (Array.isArray(data.data)) {
        metaCache = data.data;
      }
      closeDeleteSaveModal();
  
      if (
        window.activeSession?.type === 'save' &&
        window.activeSession.id === saveId
      ) {
        sidebarActiveSaveId = null;
        if (typeof showHomeView === 'function') {
          showHomeView();
        }
      } else if (sidebarActiveSaveId === saveId) {
        sidebarActiveSaveId = null;
      }
  
      renderSaveList();
    } catch (err) {
      closeDeleteSaveModal();
      window.alert(String(err.message || err));
    }
}
  
function openRenameSaveModal(saveId) {
    const save = metaCache.find(s => s.id === saveId);
    if (!save) return;
    renameTargetSaveId = saveId;
    const input = document.getElementById('rename-save-input');
    if (input) {
      input.value = save.title == null ? '' : String(save.title);
    }
    const modal = document.getElementById('rename-modal');
    if (modal) modal.classList.remove('hidden');
    if (input) {
      input.focus();
      input.select();
    }
}
  
function closeRenameSaveModal() {
    renameTargetSaveId = null;
    const modal = document.getElementById('rename-modal');
    if (modal) modal.classList.add('hidden');
}
  
async function confirmRenameSave() {
    const saveId = renameTargetSaveId;
    if (!saveId) return;
    const input = document.getElementById('rename-save-input');
    const title = input ? input.value : '';
    try {
        await patchSaveMeta(saveId, { title });
        closeRenameSaveModal();
        if (
        window.activeSession?.type === 'save' &&
        window.activeSession.id === saveId
        ) {
        window.activeSession.title = title;
        if (typeof persistViewSession === 'function') {
            persistViewSession(window.activeSession);
        }
        if (typeof syncChatViewTitle === 'function') {
            syncChatViewTitle();
        }
        }
        renderSaveList();
    } catch (_) {
        closeRenameSaveModal();
    }
}

async function handleSaveMenuAction(action) {
    const saveId = menuTargetSaveId;
    closeSaveMenu();
    if (!saveId) return;
    const save = metaCache.find(s => s.id === saveId);
    if (!save) return;
  
    if (action === 'pin') {
      try {
        await patchSaveMeta(saveId, { pinned: !save.pinned });
        renderSaveList();
      } catch (_) {}
      return;
    }
  
    if (action === 'copy') {
      try {
        await duplicateSave(saveId);
      } catch (err) {
        window.alert(String(err.message || err));
      }
      return;
    }
  
    if (action === 'rename') {
      openRenameSaveModal(saveId);
      return;
    }
  
    if (action === 'delete') {
      openDeleteSaveModal(saveId);
      return;
    }
}

async function loadSavesList() {
  await fetchMeta();
  renderSaveList();
}

function bindSavesListUi() {
    const search = document.getElementById('save-search');
    if (search && search.dataset.bound !== '1') {
      search.dataset.bound = '1';
      search.addEventListener('input', () => renderSaveList());
    }
  
    const menu = document.getElementById('save-menu');
    if (menu && menu.dataset.bound !== '1') {
      menu.dataset.bound = '1';
      menu.querySelectorAll('[data-action]').forEach(btn => {
        btn.addEventListener('click', () => {
          handleSaveMenuAction(btn.dataset.action);
        });
      });
    }
  
    if (document.documentElement.dataset.saveMenuOutside !== '1') {
      document.documentElement.dataset.saveMenuOutside = '1';
      document.addEventListener('click', e => {
        if (e.target.closest('#save-menu') || e.target.closest('.save-menu-btn')) return;
        closeSaveMenu();
      });
    }
  
    const consultBtn = document.getElementById('btn-consult');
    if (consultBtn && consultBtn.dataset.saveActiveBound !== '1') {
      consultBtn.dataset.saveActiveBound = '1';
      consultBtn.addEventListener('click', () => {
        clearSidebarSaveActive();
      });
    }
  
    const homeBtn = document.getElementById('btn-home');
    if (homeBtn && homeBtn.dataset.saveActiveBound !== '1') {
      homeBtn.dataset.saveActiveBound = '1';
      homeBtn.addEventListener('click', () => {
        clearSidebarSaveActive();
      });
    }
  
    const cancelDeleteBtn = document.getElementById('btn-cancel-delete');
    if (cancelDeleteBtn && cancelDeleteBtn.dataset.bound !== '1') {
      cancelDeleteBtn.dataset.bound = '1';
      cancelDeleteBtn.addEventListener('click', () => {
        closeDeleteSaveModal();
      });
    }
  
    const confirmDeleteBtn = document.getElementById('btn-confirm-delete');
    if (confirmDeleteBtn && confirmDeleteBtn.dataset.bound !== '1') {
      confirmDeleteBtn.dataset.bound = '1';
      confirmDeleteBtn.addEventListener('click', () => {
        confirmDeleteSave();
      });
    }
  
    const cancelRenameBtn = document.getElementById('btn-cancel-rename');
    if (cancelRenameBtn && cancelRenameBtn.dataset.bound !== '1') {
      cancelRenameBtn.dataset.bound = '1';
      cancelRenameBtn.addEventListener('click', () => {
        closeRenameSaveModal();
      });
    }
  
    const confirmRenameBtn = document.getElementById('btn-confirm-rename');
    if (confirmRenameBtn && confirmRenameBtn.dataset.bound !== '1') {
      confirmRenameBtn.dataset.bound = '1';
      confirmRenameBtn.addEventListener('click', () => {
        confirmRenameSave();
      });
    }
  
    const renameInput = document.getElementById('rename-save-input');
    if (renameInput && renameInput.dataset.bound !== '1') {
      renameInput.dataset.bound = '1';
      renameInput.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          confirmRenameSave();
        }
        if (e.key === 'Escape') {
          e.preventDefault();
          closeRenameSaveModal();
        }
      });
    }
  
    const deleteModal = document.getElementById('delete-modal');
    if (deleteModal && deleteModal.dataset.bound !== '1') {
      deleteModal.dataset.bound = '1';
      deleteModal.addEventListener('click', e => {
        if (e.target === deleteModal) closeDeleteSaveModal();
      });
    }
  
    const renameModal = document.getElementById('rename-modal');
    if (renameModal && renameModal.dataset.bound !== '1') {
      renameModal.dataset.bound = '1';
      renameModal.addEventListener('click', e => {
        if (e.target === renameModal) closeRenameSaveModal();
      });
    }
}

bindSavesListUi();