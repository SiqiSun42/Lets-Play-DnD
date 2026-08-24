const panelOverlay = document.getElementById('panel-overlay');
const panelBox = document.getElementById('panel-box');
const btnPanelClose = document.getElementById('btn-panel-close');
const panelSearch = document.getElementById('panel-sidebar-search');

const panelContents = {
  settings: document.getElementById('panel-settings'),
  notes: document.getElementById('panel-notes'),
};

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
  panelOverlay.classList.remove('hidden');
  document.body.style.overflow = 'hidden';

  panelSearch.value = '';
  panelSearch.placeholder =
    name === 'settings' ? t('searchSettings') : t('searchNotes');
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
