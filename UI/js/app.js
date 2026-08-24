initAccount()
  .then(async ({ account, settings, user }) => {
    window.AppState = { account, settings, user };
    applyAccountSettings(settings);
    applyI18n();
    if (typeof loadSavesList === 'function') {
      await loadSavesList();
    }
    if (typeof restoreViewFromSession === 'function' && restoreViewFromSession()) {
      if (
        window.activeSession?.type === 'save' &&
        window.activeSession.id &&
        typeof renderSaveList === 'function'
      ) {
        sidebarActiveSaveId = window.activeSession.id;
        renderSaveList();
      }
      return;
    }
    showHomeView();
  })
  .catch(() => {
    window.location.href = '/login.html';
  });

const sidebar = document.getElementById('sidebar');
const btnCollapse = document.getElementById('btn-collapse');

btnCollapse.addEventListener('click', () => {
  const isCollapsed = sidebar.classList.contains('collapsed');

  if (isCollapsed) {
    sidebar.classList.remove('collapsed');
    sidebar.classList.add('is-expanding');

    sidebar.addEventListener('transitionend', function onExpandDone(e) {
      if (e.propertyName !== 'width') return;
      sidebar.classList.remove('is-expanding');
      sidebar.removeEventListener('transitionend', onExpandDone);
    });
  } else {
    sidebar.classList.add('collapsed');
  }
});