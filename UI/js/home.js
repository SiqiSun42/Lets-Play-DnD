function homeMarkdownPath() {
    const lang = window.AppState?.settings?.language || localStorage.getItem('app-language') || 'zh-CN';
    return lang === 'en' ? 'content/home-en.md' : 'content/home-ch.md';
  }
  
  async function showHomeView() {
    window.activeView = 'home';
    window.activeSession = null;
    if (typeof clearPersistedViewSession === 'function') {
      clearPersistedViewSession();
    }
    const title = document.getElementById('view-title');
    const body = document.getElementById('view-body');
    if (title) title.textContent = t('home');
  
    body.innerHTML = `<div class="home-markdown md-content" id="home-markdown"></div>`;
    const el = document.getElementById('home-markdown');
  
    try {
      const res = await fetch(homeMarkdownPath(), { cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      const text = await res.text();
      el.innerHTML = renderMarkdown(text);
    } catch {
      el.innerHTML = '';
    }
  }
  
  document.getElementById('btn-home').addEventListener('click', () => {
    showHomeView();
  });