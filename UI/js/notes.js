const NOTES_FILE_PATHS = {
  inventory: 'data/inventory.md',
  plotCurMain: 'data/plot/cur_main_plot.md',
};

const NOTES_ALLY_SUBDIRS = {
  characters: 'characters/allies',
  status: 'status/allies',
  world: 'world',
};

const NOTES_WORLD_MAP_LAYERS = ['layer_1', 'layer_2', 'layer_3'];

let notesState = {
  section: 'inventory',
  expanded: { characters: false, status: false, world: false, plot: false },
  selectedId: null,
  worldMapViewId: null,
};

let notesAllyCache = {
  characters: [],
  status: [],
};

function getActiveSaveId() {
  return window.activeSession?.type === 'save' ? window.activeSession.id : null;
}

function saveDataUrl(relativePath) {
  const saveId = getActiveSaveId();
  const account = getCurrentAccount();
  if (!saveId || !account) return null;
  return `Account/${account}/Saves/${saveId}/${relativePath}`;
}

async function fetchSaveMarkdown(relativePath) {
  const url = saveDataUrl(relativePath);
  if (!url) return null;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) return null;
  return res.text();
}

async function fetchNotesFileList(subdir) {
  const saveId = getActiveSaveId();
  if (!subdir || !saveId) return [];
  const res = await fetch(
    `api/save/notes/list?save_id=${encodeURIComponent(saveId)}&subdir=${encodeURIComponent(subdir)}`,
    { cache: 'no-store' }
  );
  if (!res.ok) return [];
  const data = await res.json().catch(() => ({}));
  return data.files || [];
}

async function fetchNotesAllyList(section) {
  const subdir = NOTES_ALLY_SUBDIRS[section];
  return fetchNotesFileList(subdir);
}

async function fetchSaveJson(relativePath) {
  const url = saveDataUrl(relativePath);
  if (!url) return null;
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) return null;
  return res.json().catch(() => null);
}

async function resolveCurrentLocation() {
  const info = await fetchSaveJson('data/current_info.json');
  const location = (info?.current_location || '').trim();
  if (!location) return null;

  const path = `data/world/${location}.md`;
  const text = await fetchSaveMarkdown(path);
  if (text === null) return null;
  return { path, title: location, text };
}

async function resolveWorldLocationById(locationId) {
  const id = (locationId || '').trim();
  if (!id) return null;
  const path = `data/world/${id}.md`;
  const text = await fetchSaveMarkdown(path);
  if (text === null) return null;
  return { path, title: id, text };
}

async function fetchWorldMapData() {
  return fetchSaveJson('data/world/map.json');
}

function renderWorldMapNode(node, layerIndex) {
  const nextLayerKey = NOTES_WORLD_MAP_LAYERS[layerIndex + 1];
  const children = nextLayerKey && Array.isArray(node[nextLayerKey]) ? node[nextLayerKey] : [];
  const childrenHtml = children.map(child => renderWorldMapNode(child, layerIndex + 1)).join('');
  return `
    <div class="world-map-node">
      <button type="button" class="world-map-item" data-location-id="${node.id}">${node.id}</button>
      ${childrenHtml ? `<div class="world-map-children">${childrenHtml}</div>` : ''}
    </div>
  `;
}

function renderWorldMapTreeHtml(mapData) {
  const roots = Array.isArray(mapData?.layer_1) ? mapData.layer_1 : [];
  if (!roots.length) {
    return `<p class="notes-empty">${t('notesMapEmpty')}</p>`;
  }
  const nodesHtml = roots.map(node => renderWorldMapNode(node, 0)).join('');
  return `<div class="world-map-tree">${nodesHtml}</div>`;
}

function bindWorldMapTree(panel) {
  panel.querySelectorAll('.world-map-item').forEach(btn => {
    btn.addEventListener('click', () => {
      notesState.worldMapViewId = btn.dataset.locationId;
      renderNotesContent();
    });
  });
}

function syncPanelBackButton() {
  const btn = document.getElementById('btn-panel-back');
  if (!btn) return;
  const show =
    notesState.section === 'world' &&
    notesState.selectedId === 'world_map' &&
    notesState.worldMapViewId;
  btn.classList.toggle('hidden', !show);
}

async function renderWorldMapContent(panel) {
  if (notesState.worldMapViewId) {
    const resolved = await resolveWorldLocationById(notesState.worldMapViewId);
    if (!resolved) {
      panel.innerHTML = notesPageShell(
        notesState.worldMapViewId,
        `<p class="notes-empty">${t('notesFileMissing')}</p>`
      );
      syncPanelBackButton();
      return;
    }
    panel.innerHTML = notesPageShell(resolved.title, '');
    const el = document.getElementById('notes-markdown');
    if (el) el.innerHTML = renderMarkdown(resolved.text);
    syncPanelBackButton();
    return;
  }

  const mapData = await fetchWorldMapData();
  panel.innerHTML = notesPageShell(t('notesWorldMap'), renderWorldMapTreeHtml(mapData));
  bindWorldMapTree(panel);
  syncPanelBackButton();
}

function notesSectionLabel(section) {
  const keys = {
    inventory: 'notesInventory',
    characters: 'notesCharacters',
    status: 'notesStatus',
    world: 'notesWorld',
    plot: 'notesPlot',
    history: 'notesHistory',
  };
  return t(keys[section] || section);
}

function isNotesLeafActive(section, id) {
  if (notesState.section !== section) return false;
  if (section === 'inventory' || section === 'history') return true;
  return notesState.selectedId === id;
}

function sidebarItemHtml(section, label, extraClass) {
  const active = notesState.section === section && !extraClass ? ' active' : '';
  return `
    <button type="button" class="panel-sidebar-item${active}${extraClass || ''}" data-section="${section}">
      ${label}
    </button>
  `;
}

function sidebarSubItemHtml(section, id, label) {
  const active = isNotesLeafActive(section, id) ? ' active' : '';
  return `
    <button type="button" class="panel-sidebar-subitem${active}" data-section="${section}" data-id="${id}">
      ${label}
    </button>
  `;
}

function renderNotesNav() {
  const nav = document.getElementById('panel-sidebar-nav');
  if (!nav) return;

  if (typeof isConsultNotesMode === 'function' && isConsultNotesMode()) {
    nav.innerHTML = sidebarItemHtml('history', notesSectionLabel('history'));
    nav.querySelectorAll('.panel-sidebar-item[data-section="history"]').forEach(btn => {
      btn.addEventListener('click', () => selectNotesSection('history'));
    });
    return;
  }

  const charactersExpanded = notesState.expanded.characters;
  const statusExpanded = notesState.expanded.status;
  const worldExpanded = notesState.expanded.world;
  const plotExpanded = notesState.expanded.plot;

  const charactersSubs = notesAllyCache.characters
    .map(file => sidebarSubItemHtml('characters', file.id, file.name))
    .join('');

  const statusSubs = notesAllyCache.status
    .map(file => sidebarSubItemHtml('status', file.id, file.name))
    .join('');

  const worldSubs = [
    sidebarSubItemHtml('world', 'cur_location', t('notesCurLocation')),
    sidebarSubItemHtml('world', 'world_map', t('notesWorldMap')),
  ].join('');

  const plotSubs = sidebarSubItemHtml('plot', 'cur_main_plot', t('notesCurMainPlot'));

  nav.innerHTML = `
    ${sidebarItemHtml('inventory', notesSectionLabel('inventory'))}
    <div class="panel-sidebar-group">
      <button type="button" class="panel-sidebar-item panel-sidebar-group-toggle${notesState.section === 'characters' && !notesState.selectedId ? ' active' : ''}" data-section="characters" data-toggle="characters">
        <span>${notesSectionLabel('characters')}</span>
        <span class="panel-sidebar-chevron${charactersExpanded ? ' expanded' : ''}" aria-hidden="true">›</span>
      </button>
      <div class="panel-sidebar-subnav${charactersExpanded ? '' : ' hidden'}">${charactersSubs}</div>
    </div>
    <div class="panel-sidebar-group">
      <button type="button" class="panel-sidebar-item panel-sidebar-group-toggle${notesState.section === 'status' && !notesState.selectedId ? ' active' : ''}" data-section="status" data-toggle="status">
        <span>${notesSectionLabel('status')}</span>
        <span class="panel-sidebar-chevron${statusExpanded ? ' expanded' : ''}" aria-hidden="true">›</span>
      </button>
      <div class="panel-sidebar-subnav${statusExpanded ? '' : ' hidden'}">${statusSubs}</div>
    </div>
    <div class="panel-sidebar-group">
      <button type="button" class="panel-sidebar-item panel-sidebar-group-toggle${notesState.section === 'world' && !notesState.selectedId ? ' active' : ''}" data-section="world" data-toggle="world">
        <span>${notesSectionLabel('world')}</span>
        <span class="panel-sidebar-chevron${worldExpanded ? ' expanded' : ''}" aria-hidden="true">›</span>
      </button>
      <div class="panel-sidebar-subnav${worldExpanded ? '' : ' hidden'}">${worldSubs}</div>
    </div>
    <div class="panel-sidebar-group">
      <button type="button" class="panel-sidebar-item panel-sidebar-group-toggle${notesState.section === 'plot' && !notesState.selectedId ? ' active' : ''}" data-section="plot" data-toggle="plot">
        <span>${notesSectionLabel('plot')}</span>
        <span class="panel-sidebar-chevron${plotExpanded ? ' expanded' : ''}" aria-hidden="true">›</span>
      </button>
      <div class="panel-sidebar-subnav${plotExpanded ? '' : ' hidden'}">${plotSubs}</div>
    </div>
    ${sidebarItemHtml('history', notesSectionLabel('history'))}
  `;

  nav.querySelectorAll('.panel-sidebar-item[data-section="inventory"]').forEach(btn => {
    btn.addEventListener('click', () => selectNotesSection('inventory'));
  });

  nav.querySelectorAll('.panel-sidebar-item[data-section="history"]').forEach(btn => {
    btn.addEventListener('click', () => selectNotesSection('history'));
  });

  nav.querySelectorAll('.panel-sidebar-group-toggle').forEach(btn => {
    btn.addEventListener('click', () => {
      const section = btn.dataset.toggle;
      notesState.expanded[section] = !notesState.expanded[section];
      renderNotesNav();
    });
  });

  nav.querySelectorAll('.panel-sidebar-subitem').forEach(btn => {
    btn.addEventListener('click', () => {
      selectNotesLeaf(btn.dataset.section, btn.dataset.id);
    });
  });
}

function selectNotesSection(section) {
  notesState.section = section;
  notesState.selectedId = null;
  notesState.worldMapViewId = null;
  if (section === 'history' && typeof resetHistoryPanel === 'function') {
    resetHistoryPanel();
  }
  if (section === 'inventory' || section === 'history') {
    renderNotesNav();
    renderNotesContent();
  }
}

function selectNotesLeaf(section, id) {
  notesState.section = section;
  notesState.selectedId = id;
  notesState.worldMapViewId = null;
  notesState.expanded[section] = true;
  renderNotesNav();
  renderNotesContent();
}

async function resolveNotesMarkdownPath() {
  const { section, selectedId } = notesState;
  if (section === 'inventory') return NOTES_FILE_PATHS.inventory;
  if (section === 'characters' && selectedId) {
    return `data/characters/allies/${selectedId}.md`;
  }
  if (section === 'status' && selectedId) {
    return `data/status/allies/${selectedId}.md`;
  }
  if (section === 'plot' && selectedId === 'cur_main_plot') {
    return NOTES_FILE_PATHS.plotCurMain;
  }
  return null;
}

function notesContentTitle() {
  const { section, selectedId } = notesState;
  if (section === 'inventory') return notesSectionLabel('inventory');
  if (section === 'history') return notesSectionLabel('history');
  if (section === 'world' && selectedId === 'cur_location') return t('notesCurLocation');
  if (section === 'world' && selectedId === 'world_map') return t('notesWorldMap');
  if (section === 'plot' && selectedId === 'cur_main_plot') return t('notesCurMainPlot');
  if (selectedId) return selectedId;
  return notesSectionLabel(section);
}

function notesPageShell(title, bodyHtml) {
  return `
    <div class="notes-page">
      <div class="notes-page-header">
        <h2 class="notes-page-title">${title}</h2>
        <div class="notes-page-divider"></div>
      </div>
      <div class="notes-page-body md-content" id="notes-markdown">${bodyHtml || ''}</div>
    </div>
  `;
}

async function renderNotesContent() {
  const panel = document.getElementById('panel-notes');
  if (!panel) return;

  if (notesState.section === 'history') {
    syncPanelBackButton();
    if (typeof renderHistoryPanel === 'function') {
      await renderHistoryPanel(panel);
    }
    return;
  }

  if (!getActiveSaveId() && !(typeof isConsultNotesMode === 'function' && isConsultNotesMode())) {
    panel.innerHTML = `<p class="notes-empty">${t('notesNoSave')}</p>`;
    return;
  }

  if (notesState.section === 'world') {
    if (notesState.selectedId === 'world_map') {
      await renderWorldMapContent(panel);
      return;
    }
    if (notesState.selectedId === 'cur_location') {
      syncPanelBackButton();
      const resolved = await resolveCurrentLocation();
      if (!resolved) {
        panel.innerHTML = notesPageShell(
          t('notesCurLocation'),
          `<p class="notes-empty">${t('notesLocationMissing')}</p>`
        );
        return;
      }
      panel.innerHTML = notesPageShell(resolved.title, '');
      const el = document.getElementById('notes-markdown');
      const text = await fetchSaveMarkdown(resolved.path);
      if (!el) return;
      if (text === null) {
        el.innerHTML = `<p class="notes-empty">${t('notesFileMissing')}</p>`;
        return;
      }
      el.innerHTML = renderMarkdown(text);
      return;
    }
    syncPanelBackButton();
    panel.innerHTML = notesPageShell(notesSectionLabel('world'), '');
    return;
  }

  syncPanelBackButton();
  const path = await resolveNotesMarkdownPath();
  if (!path) {
    panel.innerHTML = notesPageShell(notesContentTitle(), '');
    return;
  }

  const title = notesContentTitle();
  panel.innerHTML = notesPageShell(title, '');

  const el = document.getElementById('notes-markdown');
  const text = await fetchSaveMarkdown(path);
  if (!el) return;
  if (text === null) {
    el.innerHTML = `<p class="notes-empty">${t('notesFileMissing')}</p>`;
    return;
  }
  el.innerHTML = renderMarkdown(text);
}

async function loadNotesAllyLists() {
  const [characters, status] = await Promise.all([
    fetchNotesAllyList('characters'),
    fetchNotesAllyList('status'),
  ]);
  notesAllyCache.characters = characters;
  notesAllyCache.status = status;
}

async function initNotesPanel() {
  if (typeof isConsultNotesMode === 'function' && isConsultNotesMode()) {
    notesState.section = 'history';
    notesState.selectedId = null;
    notesState.worldMapViewId = null;
    if (typeof resetHistoryPanel === 'function') resetHistoryPanel();
  }
  await loadNotesAllyLists();
  renderNotesNav();
  await renderNotesContent();
}

document.getElementById('btn-panel-back')?.addEventListener('click', () => {
  if (notesState.section !== 'world' || notesState.selectedId !== 'world_map') return;
  notesState.worldMapViewId = null;
  renderNotesContent();
});
