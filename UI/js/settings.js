const MODELS = [
  { id: 'deepseek', labelKey: 'modelDeepseek' },
];

const THEMES = [
  { id: 'night', labelKey: 'themeNight' },
  { id: 'day', labelKey: 'themeDay' },
  { id: 'spring', labelKey: 'themeSpring' },
  { id: 'forest', labelKey: 'themeForest' },
  { id: 'book', labelKey: 'themeBook' },
  { id: 'sky', labelKey: 'themeSky' },
  { id: 'flower', labelKey: 'themeFlower' },
  { id: 'stars', labelKey: 'themeStars' },
];

  const LANGUAGES = [
    { id: 'zh-CN', label: '简体中文' },
    { id: 'en', label: 'English' },
  ];

  let activeSettingsPage = 'display';
  
  function languageLabel(id) {
    return LANGUAGES.find(lang => lang.id === id)?.label || '简体中文';
  }

  function renderDisplayPage() {
    const current = window.AppState?.settings?.theme || 'stars';
  
    const row1 = THEMES.slice(0, 4).map(theme => themeButtonHtml(theme, current)).join('');
    const row2 = THEMES.slice(4, 8).map(theme => themeButtonHtml(theme, current)).join('');
  
    document.getElementById('panel-settings').innerHTML = `
      <h2 class="settings-page-title">${t('display')}</h2>
      <section class="settings-section">
        <h3 class="settings-section-title">${t('backgroundColor')}</h3>
        <div class="settings-theme-row">${row1}</div>
        <div class="settings-theme-row">${row2}</div>
      </section>
    `;
  
    document.querySelectorAll('.settings-theme-btn').forEach(btn => {
      btn.addEventListener('click', () => selectTheme(btn.dataset.theme));
    });
  }
  
  function themeButtonHtml(theme, current) {
    const active = theme.id === current ? ' active' : '';
    return `
      <button type="button" class="settings-theme-btn${active}" data-theme="${theme.id}">
        <span class="settings-theme-swatch settings-theme-swatch--${theme.id}"></span>
        <span>${t(theme.labelKey)}</span>
      </button>
    `;
  }

  function renderLanguagePage() {
    const current = window.AppState?.settings?.language || 'zh-CN';
  
    const optionsHtml = LANGUAGES.map(lang => `
      <button type="button" data-value="${lang.id}" class="${lang.id === current ? 'active' : ''}">
        ${lang.label}
      </button>
    `).join('');
  
    document.getElementById('panel-settings').innerHTML = `
      <h2 class="settings-page-title">${t('language')}</h2>
      <section class="settings-section">
        <div class="settings-field-row">
          <h3 class="settings-section-title">${t('uiLanguage')}</h3>
          <div class="settings-picker">
            <button type="button" class="settings-picker-btn" id="settings-language-btn">
              ${languageLabel(current)}
            </button>
            <div class="settings-picker-menu hidden" id="settings-language-menu">
              ${optionsHtml}
            </div>
          </div>
        </div>
      </section>
    `;
  
    const btn = document.getElementById('settings-language-btn');
    const menu = document.getElementById('settings-language-menu');
  
    btn.addEventListener('click', e => {
      e.stopPropagation();
      menu.classList.toggle('hidden');
    });
  
    menu.querySelectorAll('button').forEach(option => {
      option.addEventListener('click', () => {
        selectLanguage(option.dataset.value);
        btn.textContent = languageLabel(option.dataset.value);
        menu.querySelectorAll('button').forEach(b => b.classList.remove('active'));
        option.classList.add('active');
        menu.classList.add('hidden');
      });
    });
  }
  
  async function selectLanguage(language) {
    document.documentElement.lang = language;
    if (window.AppState?.settings) {
      window.AppState.settings.language = language;
    }
    await patchFile('settings.json', { language });

    await fetch('api/meta/patch-by-id', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: 'consult',
        patch: { in_game_language: language },
      }),
    });
    
    if (window.activeView === 'home' && typeof showHomeView === 'function') {
      showHomeView();
    } else if (
      window.activeView === 'chat' &&
      window.activeSession?.type === 'consult' &&
      typeof loadConsultMessages === 'function'
    ) {
      window.activeSession.language = language;
      if (typeof persistViewSession === 'function') {
        persistViewSession(window.activeSession);
      }
      syncChatViewTitle();
      if (typeof applyChatInputPlaceholder === 'function') {
        applyChatInputPlaceholder();
      }
      loadConsultMessages();
    } else if (typeof syncChatViewTitle === 'function') {
      syncChatViewTitle();
    }

    applyI18n();
    initSettingsPanel();
    localStorage.setItem('app-language', language);
  }
  
  async function selectTheme(themeId) {
    document.documentElement.setAttribute('data-color-theme', themeId);
    if (window.AppState?.settings) {
      window.AppState.settings.theme = themeId;
    }
    await patchFile('settings.json', { theme: themeId });
    document.querySelectorAll('.settings-theme-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.theme === themeId);
    });
  }
  
  function initSettingsPanel() {
    const nav = document.getElementById('panel-sidebar-nav');
    nav.innerHTML = `
      <button type="button" class="panel-sidebar-item${activeSettingsPage === 'display' ? ' active' : ''}" data-page="display">${t('display')}</button>
      <button type="button" class="panel-sidebar-item${activeSettingsPage === 'language' ? ' active' : ''}" data-page="language">${t('language')}</button>
      <button type="button" class="panel-sidebar-item${activeSettingsPage === 'model' ? ' active' : ''}" data-page="model">${t('modelSettings')}</button>
    `;
  
    nav.querySelectorAll('.panel-sidebar-item').forEach(btn => {
      btn.addEventListener('click', () => {
        activeSettingsPage = btn.dataset.page;
        nav.querySelectorAll('.panel-sidebar-item').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
    
        if (activeSettingsPage === 'display') renderDisplayPage();
        else if (activeSettingsPage === 'language') renderLanguagePage();
        else if (activeSettingsPage === 'model') renderModelPage();
      });
    });
    
    if (activeSettingsPage === 'language') renderLanguagePage();
    else if (activeSettingsPage === 'model') renderModelPage();
    else renderDisplayPage();
  }

  function modelLabel(id) {
    const m = MODELS.find(x => x.id === id);
    return m ? t(m.labelKey) : t('modelDeepseek');
  }
  
  async function renderModelPage() {
    const current = window.AppState?.settings?.model || 'deepseek';
    const hasKey = !!window.AppState?.user?.hasApiKey;
  
    const optionsHtml = MODELS.map(m => `
      <button type="button" data-value="${m.id}" class="${m.id === current ? 'active' : ''}">
        ${t(m.labelKey)}
      </button>
    `).join('');
  
    document.getElementById('panel-settings').innerHTML = `
      <h2 class="settings-page-title">${t('modelSettings')}</h2>
      <section class="settings-section">
        <div class="settings-field-row">
          <h3 class="settings-section-title">${t('modelProvider')}</h3>
          <div class="settings-picker">
            <button type="button" class="settings-picker-btn" id="settings-model-btn">${modelLabel(current)}</button>
            <div class="settings-picker-menu hidden" id="settings-model-menu">${optionsHtml}</div>
          </div>
        </div>
      </section>
      <section class="settings-section">
        <div class="settings-field-row">
          <h3 class="settings-section-title">
            ${t('apiKey')}: <span id="settings-api-status">${hasKey ? t('apiKeyStatusSet') : t('apiKeyStatusEmpty')}</span>
          </h3>
          <button type="button" class="settings-api-btn" id="btn-edit-api-key">${t('editApiKey')}</button>
        </div>
        <div class="settings-api-editor hidden" id="settings-api-editor">
          <input id="settings-api-key" type="password" placeholder="${t('apiKeyPlaceholder')}" autocomplete="off">
          <button type="button" class="settings-api-btn" id="btn-save-api-key">${t('saveApiKey')}</button>
        </div>
      </section>
    `;
  
    const btn = document.getElementById('settings-model-btn');
    const menu = document.getElementById('settings-model-menu');
    btn.addEventListener('click', e => {
      e.stopPropagation();
      menu.classList.toggle('hidden');
    });
    menu.querySelectorAll('button').forEach(option => {
      option.addEventListener('click', async () => {
        await selectModel(option.dataset.value);
        btn.textContent = modelLabel(option.dataset.value);
        menu.querySelectorAll('button').forEach(b => b.classList.remove('active'));
        option.classList.add('active');
        menu.classList.add('hidden');
      });
    });
  
    document.getElementById('btn-edit-api-key').addEventListener('click', () => {
      document.getElementById('btn-edit-api-key').classList.add('hidden');
      document.getElementById('settings-api-editor').classList.remove('hidden');
      const input = document.getElementById('settings-api-key');
      input.value = '';
      input.focus();
    });
    document.getElementById('btn-save-api-key').addEventListener('click', saveApiKey);
  }
  
  async function selectModel(modelId) {
    if (window.AppState?.settings) window.AppState.settings.model = modelId;
    await patchFile('settings.json', { model: modelId });
  }
  
  async function saveApiKey() {
    const input = document.getElementById('settings-api-key');
    const saveBtn = document.getElementById('btn-save-api-key');
    const editBtn = document.getElementById('btn-edit-api-key');
    const editor = document.getElementById('settings-api-editor');
    const api_key = input.value.trim();
  
    function closeEditor() {
      editor.classList.add('hidden');
      editBtn.classList.remove('hidden');
      input.value = '';
      saveBtn.disabled = false;
      saveBtn.textContent = t('saveApiKey');
    }
  
    if (!api_key) {
      closeEditor();
      return;
    }
  
    saveBtn.disabled = true;
    saveBtn.textContent = t('apiKeySaving');
  
    try {
      const res = await fetch('api/api-key', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key }),
      });
      if (!res.ok) {
        closeEditor();
        return;
      }
      if (window.AppState?.user) window.AppState.user.hasApiKey = true;
      document.getElementById('settings-api-status').textContent = t('apiKeyStatusSet');
      await new Promise(r => setTimeout(r, 400));
      closeEditor();
    } catch {
      closeEditor();
    }
  }
  
  async function clearApiKey() {
    const res = await fetch('api/api-key', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clear: true }),
    });
    if (!res.ok) return;
    if (window.AppState?.user) window.AppState.user.hasApiKey = false;
    renderModelPage();
  }