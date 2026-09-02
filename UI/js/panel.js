const panelOverlay = document.getElementById('panel-overlay');
const panelBox = document.getElementById('panel-box');
const btnPanelClose = document.getElementById('btn-panel-close');

const panelContents = {
  settings: document.getElementById('panel-settings'),
  notes: document.getElementById('panel-notes'),
};

const panelSidebarTitle = document.getElementById('panel-sidebar-title');

const PANEL_SIDEBAR_META = {
  settings: 'panelSettings',
  notes: 'panelNotes',
};

function syncPanelSidebarTitle(name) {
  const panelName = name ?? activePanel;
  const labelKey = PANEL_SIDEBAR_META[panelName];
  if (!panelSidebarTitle || !labelKey) return;
  panelSidebarTitle.textContent = t(labelKey);
}

window.syncPanelSidebarTitle = syncPanelSidebarTitle;

let activePanel = null;

function openPanel(name) {
  if (!panelContents[name]) return;

  if (name === 'settings') {
    initSettingsPanel();
  } else if (name === 'notes') {
    initNotesPanel();
  }

  Object.entries(panelContents).forEach(([key, el]) => {
    el.classList.toggle('hidden', key !== name);
  });

  activePanel = name;
  syncPanelSidebarTitle(name);
  panelOverlay.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
}

function closePanel() {
  panelOverlay.classList.add('hidden');
  activePanel = null;
  document.body.style.overflow = '';
}

btnPanelClose.addEventListener('click', closePanel);

document.getElementById('btn-settings').addEventListener('click', () => {
  openPanel('settings');
});

document.getElementById('btn-note').addEventListener('click', () => {
  openPanel('notes');
});
