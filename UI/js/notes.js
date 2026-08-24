let activeNotesPage = 'note1';

function initNotesPanel() {
  const nav = document.getElementById('panel-sidebar-nav');
  nav.innerHTML = `
    <button type="button" class="panel-sidebar-item${activeNotesPage === 'note1' ? ' active' : ''}" data-page="note1">${t('placeholderNote1')}</button>
    <button type="button" class="panel-sidebar-item${activeNotesPage === 'note2' ? ' active' : ''}" data-page="note2">${t('placeholderNote2')}</button>
  `;

  nav.querySelectorAll('.panel-sidebar-item').forEach(btn => {
    btn.addEventListener('click', () => {
      activeNotesPage = btn.dataset.page;
      nav.querySelectorAll('.panel-sidebar-item').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderNotesPage();
    });
  });

  renderNotesPage();
}

function renderNotesPage() {
  const title = activeNotesPage === 'note2' ? t('placeholderNote2') : t('placeholderNote1');
  document.getElementById('panel-notes').innerHTML = `
    <h2 class="settings-page-title">${title}</h2>
  `;
}