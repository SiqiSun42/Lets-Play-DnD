const accountOptionsMenu = document.getElementById('account-options-menu');
const accountOverlay = document.getElementById('account-overlay');
const btnAccountOptions = document.getElementById('btn-account-options');
const btnAccountClose = document.getElementById('btn-account-close');

function positionMenu(menu, rect) {
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

  function closeAccountOptionsMenu() {
    accountOptionsMenu.classList.add('hidden');
  }
  
  function openAccountOptionsMenu(e) {
    e.stopPropagation();
    const willOpen = accountOptionsMenu.classList.contains('hidden');
    closeAccountOptionsMenu();
    if (willOpen) {
      positionMenu(accountOptionsMenu, e.currentTarget.getBoundingClientRect());
    }
  }

  function openAccountManage() {
    closeAccountOptionsMenu();
    renderAccountManage();
    accountOverlay.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  }
  
  function closeAccountManage() {
    accountOverlay.classList.add('hidden');
    document.body.style.overflow = '';
  }

  async function doLogout() {
    closeAccountOptionsMenu();
    closeAccountManage();
    if (typeof clearPersistedViewSession === 'function') {
      clearPersistedViewSession();
    }
    await logoutAccount();
    await fadeTo('/login.html');
  }

btnAccountOptions.addEventListener('click', openAccountOptionsMenu);

btnAccountClose.addEventListener('click', closeAccountManage);

accountOptionsMenu.querySelectorAll('[data-action]').forEach(btn => {
  btn.addEventListener('click', () => {
    const action = btn.dataset.action;
    closeAccountOptionsMenu();
    if (action === 'switch-account') {
      openAccountManage();
    } else if (action === 'logout') {
      doLogout();
    }
  });
});

document.addEventListener('click', e => {
  if (
    !e.target.closest('#account-options-menu') &&
    !e.target.closest('#btn-account-options')
  ) {
    closeAccountOptionsMenu();
  }
});

function displayEmail(email) {
  if (!email || String(email).endsWith('@local.invalid')) {
    return t('emailNotSet');
  }
  return email;
}

function renderAccountManage() {
  const user = window.AppState?.user || { username: getCurrentAccount(), email: '' };
  const body = document.getElementById('account-manage-body');
  body.innerHTML = `
    <h2 class="account-manage-title">${t('accountManageTitle')}</h2>
    <div class="account-manage-fields">
      <div class="account-manage-field">
        <div class="account-manage-label">${t('username')}</div>
        <div class="account-manage-value" id="account-manage-username">${user.username}</div>
      </div>
      <div class="account-manage-field">
        <div class="account-manage-label">${t('email')}</div>
        <div class="account-manage-value" id="account-manage-email">${displayEmail(user.email)}</div>
      </div>
    </div>
    <div class="account-manage-actions">
      <button type="button" class="account-manage-action" id="btn-edit-password">${t('editPassword')}</button>
      <button type="button" class="account-manage-action" id="btn-edit-email">${t('editEmail')}</button>
      <button type="button" class="account-manage-action" id="btn-delete-account">${t('deleteAccount')}</button>
      <button type="button" class="account-manage-action" id="btn-logout">${t('logout')}</button>
    </div>
  `;
  document.getElementById('btn-logout').addEventListener('click', doLogout);
  document.getElementById('btn-edit-password').addEventListener('click', renderChangePassword);
  document.getElementById('btn-edit-email').addEventListener('click', renderChangeEmail);
  document.getElementById('btn-delete-account').addEventListener('click', renderDeleteAccount);
}

const PASSWORD_RE = /^[A-Za-z0-9_]{6,64}$/;

function eyeClosedSvg() {
  return `
    <svg class="account-eye-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path fill="currentColor" d="M12 5c-5 0-9.3 3.1-11 7 1.7 3.9 6 7 11 7s9.3-3.1 11-7c-1.7-3.9-6-7-11-7zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/>
      <path fill="currentColor" d="M3.3 3.3 20.7 20.7l-1.4 1.4L1.9 4.7z"/>
    </svg>
  `;
}

function eyeOpenSvg() {
  return `
    <svg class="account-eye-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path fill="currentColor" d="M12 5c-5 0-9.3 3.1-11 7 1.7 3.9 6 7 11 7s9.3-3.1 11-7c-1.7-3.9-6-7-11-7zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/>
    </svg>
  `;
}

function bindAccountPasswordEyes() {
  document.querySelectorAll('.account-eye').forEach(btn => {
    const input = document.getElementById(btn.dataset.eyeFor);
    if (!input) return;
    btn.addEventListener('click', () => {
      const showing = input.type === 'text';
      if (showing) {
        input.type = 'password';
        btn.innerHTML = eyeClosedSvg();
        btn.setAttribute('aria-label', 'show password');
      } else {
        input.type = 'text';
        btn.innerHTML = eyeOpenSvg();
        btn.setAttribute('aria-label', 'hide password');
      }
    });
  });
}

function clearPasswordFieldErrors() {
  ['pwd-old', 'pwd-new', 'pwd-confirm'].forEach(id => {
    document.getElementById(`${id}-error`).textContent = '';
    document.getElementById(id).classList.remove('is-invalid');
  });
}

function showPasswordFieldError(inputId, errorId, message) {
  const input = document.getElementById(inputId);
  document.getElementById(errorId).textContent = message;
  input.classList.add('is-invalid');
  input.focus();
}

function renderChangePassword() {
  const body = document.getElementById('account-manage-body');
  body.innerHTML = `
    <h2 class="account-manage-title">${t('editPasswordTitle')}</h2>
    <form class="account-form" id="change-password-form">
      <div class="account-form-field">
        <div class="account-field-head">
          <label for="pwd-old">${t('oldPassword')}</label>
          <span class="account-field-error" id="pwd-old-error"></span>
        </div>
        <div class="account-password-wrap">
          <input id="pwd-old" type="password" placeholder="${t('oldPasswordPlaceholder')}" autocomplete="current-password">
          <button type="button" class="account-eye" data-eye-for="pwd-old" aria-label="show password">${eyeClosedSvg()}</button>
        </div>
      </div>
      <div class="account-form-field">
        <div class="account-field-head">
          <div class="account-label-with-help">
            <label for="pwd-new">${t('newPassword')}</label>
            <button type="button" class="account-help" tabindex="-1">
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>
                <path fill="currentColor" d="M12 17a1.2 1.2 0 1 1 0-2.4A1.2 1.2 0 0 1 12 17zm1-4.2h-2c0-1.7 1.6-1.9 1.6-3.1 0-.7-.5-1.2-1.3-1.2-.9 0-1.4.5-1.4 1.4H8.5C8.5 8.2 10 7 12.1 7c1.9 0 3.2 1.1 3.2 2.7 0 1.8-1.7 2.2-2.3 3.1z"/>
              </svg>
              <span class="account-help-tip">${t('tipPassword')}</span>
            </button>
          </div>
          <span class="account-field-error" id="pwd-new-error"></span>
        </div>
        <div class="account-password-wrap">
          <input id="pwd-new" type="password" placeholder="${t('newPasswordPlaceholder')}" autocomplete="new-password">
          <button type="button" class="account-eye" data-eye-for="pwd-new" aria-label="show password">${eyeClosedSvg()}</button>
        </div>
      </div>
      <div class="account-form-field">
        <div class="account-field-head">
          <label for="pwd-confirm">${t('confirmNewPassword')}</label>
          <span class="account-field-error" id="pwd-confirm-error"></span>
        </div>
        <div class="account-password-wrap">
          <input id="pwd-confirm" type="password" placeholder="${t('confirmNewPasswordPlaceholder')}" autocomplete="new-password">
          <button type="button" class="account-eye" data-eye-for="pwd-confirm" aria-label="show password">${eyeClosedSvg()}</button>
        </div>
      </div>
      <div class="account-form-actions">
        <button type="button" class="account-form-btn" id="btn-pwd-back">${t('back')}</button>
        <button type="submit" class="account-form-btn account-form-btn-primary" id="btn-pwd-save">${t('savePassword')}</button>
      </div>
    </form>
  `;

  bindAccountPasswordEyes();
  document.getElementById('btn-pwd-back').addEventListener('click', renderAccountManage);
  document.getElementById('change-password-form').addEventListener('submit', onSavePassword);
}

async function onSavePassword(e) {
  e.preventDefault();
  clearPasswordFieldErrors();

  const oldPassword = document.getElementById('pwd-old').value;
  const newPassword = document.getElementById('pwd-new').value;
  const confirm = document.getElementById('pwd-confirm').value;

  if (!oldPassword) {
    showPasswordFieldError('pwd-old', 'pwd-old-error', t('pwdMissingOld'));
    return;
  }
  if (!newPassword) {
    showPasswordFieldError('pwd-new', 'pwd-new-error', t('pwdMissingNew'));
    return;
  }
  if (!PASSWORD_RE.test(newPassword)) {
    showPasswordFieldError('pwd-new', 'pwd-new-error', t('pwdInvalidNew'));
    return;
  }
  if (!confirm) {
    showPasswordFieldError('pwd-confirm', 'pwd-confirm-error', t('pwdMissingConfirm'));
    return;
  }
  if (newPassword !== confirm) {
    showPasswordFieldError('pwd-confirm', 'pwd-confirm-error', t('pwdConfirmMismatch'));
    return;
  }

  const saveBtn = document.getElementById('btn-pwd-save');
  try {
    const res = await fetch('/api/change-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        old_password: oldPassword,
        new_password: newPassword,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (data.error === 'wrong_old_password') {
        showPasswordFieldError('pwd-old', 'pwd-old-error', t('pwdWrongOld'));
      } else {
        showPasswordFieldError('pwd-old', 'pwd-old-error', t('pwdWrongOld'));
      }
      return;
    }
    saveBtn.disabled = true;
    saveBtn.classList.add('is-success');
    saveBtn.textContent = t('pwdChangeSuccess');
    setTimeout(() => {
      renderAccountManage();
    }, 500);
  } catch {
    showPasswordFieldError('pwd-old', 'pwd-old-error', t('pwdWrongOld'));
  }
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function renderChangeEmail() {
  const body = document.getElementById('account-manage-body');
  const current = window.AppState?.user?.email || '';
  const shown =
    current && !String(current).endsWith('@local.invalid') ? current : '';

  body.innerHTML = `
    <h2 class="account-manage-title">${t('editEmailTitle')}</h2>
    <form class="account-form" id="change-email-form">
      <div class="account-form-field">
        <div class="account-field-head">
          <div class="account-label-with-help">
            <label for="email-new">${t('newEmail')}</label>
            <button type="button" class="account-help" tabindex="-1">
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>
                <path fill="currentColor" d="M12 17a1.2 1.2 0 1 1 0-2.4A1.2 1.2 0 0 1 12 17zm1-4.2h-2c0-1.7 1.6-1.9 1.6-3.1 0-.7-.5-1.2-1.3-1.2-.9 0-1.4.5-1.4 1.4H8.5C8.5 8.2 10 7 12.1 7c1.9 0 3.2 1.1 3.2 2.7 0 1.8-1.7 2.2-2.3 3.1z"/>
              </svg>
              <span class="account-help-tip">${t('tipEditEmail')}</span>
            </button>
          </div>
          <span class="account-field-error" id="email-new-error"></span>
        </div>      
          <div class="account-email-wrap">
            <input id="email-new" type="text" value="${shown}" placeholder="${t('newEmailPlaceholder')}" autocomplete="email">
            <button type="button" class="account-email-clear" id="btn-email-unbind" aria-label="${t('unbindEmail')}">
              <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
                <path fill="currentColor" d="M9 3h6l1 2h4v2H4V5h4l1-2zm1 6h2v9h-2V9zm4 0h2v9h-2V9zM7 9h2v9H7V9zm-1 12h12a1 1 0 0 0 1-1V7H5v13a1 1 0 0 0 1 1z"/>
              </svg>
            </button>
          </div>
        </div>
        <div class="account-form-actions">
        <button type="button" class="account-form-btn" id="btn-email-back">${t('back')}</button>
        <button type="submit" class="account-form-btn account-form-btn-primary" id="btn-email-save">${t('savePassword')}</button>
      </div>
    </form>
  `;

  document.getElementById('btn-email-back').addEventListener('click', renderAccountManage);
  document.getElementById('btn-email-unbind').addEventListener('click', onUnbindEmail);
  document.getElementById('change-email-form').addEventListener('submit', onSaveEmail);
}

function clearEmailFieldError() {
  document.getElementById('email-new-error').textContent = '';
  document.getElementById('email-new').classList.remove('is-invalid');
}

function showEmailFieldError(message) {
  document.getElementById('email-new-error').textContent = message;
  document.getElementById('email-new').classList.add('is-invalid');
  document.getElementById('email-new').focus();
}

function applyUserUpdate(user) {
  if (window.AppState) {
    window.AppState.user = user;
  }
}

async function onSaveEmail(e) {
  e.preventDefault();
  clearEmailFieldError();
  const email = document.getElementById('email-new').value.trim();

  if (!email || !EMAIL_RE.test(email) || email.endsWith('@local.invalid')) {
    showEmailFieldError(t('emailInvalid'));
    return;
  }

  const saveBtn = document.getElementById('btn-email-save');
  try {
    const res = await fetch('/api/change-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showEmailFieldError(
        data.error === 'email_taken' ? t('emailTaken') : t('emailInvalid')
      );
      return;
    }
    applyUserUpdate(data.user);
    saveBtn.disabled = true;
    saveBtn.classList.add('is-success');
    saveBtn.textContent = t('emailChangeSuccess');
    setTimeout(() => renderAccountManage(), 500);
  } catch {
    showEmailFieldError(t('emailInvalid'));
  }
}

async function onUnbindEmail() {
  clearEmailFieldError();
  const saveBtn = document.getElementById('btn-email-save');
  try {
    const res = await fetch('/api/change-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ unbind: true }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) return;
    applyUserUpdate(data.user);
    saveBtn.disabled = true;
    saveBtn.classList.add('is-success');
    saveBtn.textContent = t('emailUnbound');
    setTimeout(() => renderAccountManage(), 500);
  } catch {}
}

function renderDeleteAccount() {
  const body = document.getElementById('account-manage-body');
  body.innerHTML = `
    <h2 class="account-manage-title">${t('deleteAccountTitle')}</h2>
    <form class="account-form" id="delete-account-form">
      <div class="account-form-field">
        <div class="account-field-head">
          <label for="delete-password">${t('deleteAccountHint')}</label>
          <span class="account-field-error" id="delete-password-error"></span>
        </div>
        <div class="account-password-wrap">
          <input id="delete-password" type="password" placeholder="${t('deleteAccountPlaceholder')}" autocomplete="current-password">
          <button type="button" class="account-eye" data-eye-for="delete-password" aria-label="show password">${eyeClosedSvg()}</button>
        </div>
      </div>
      <div class="account-form-actions">
        <button type="button" class="account-form-btn" id="btn-delete-back">${t('back')}</button>
        <button type="submit" class="account-form-btn account-form-btn-primary" id="btn-delete-confirm">${t('deleteAccountConfirm')}</button>
      </div>
    </form>
  `;

  bindAccountPasswordEyes();
  document.getElementById('btn-delete-back').addEventListener('click', renderAccountManage);
  document.getElementById('delete-account-form').addEventListener('submit', onConfirmDeleteAccount);
}

async function onConfirmDeleteAccount(e) {
  e.preventDefault();
  const input = document.getElementById('delete-password');
  const err = document.getElementById('delete-password-error');
  err.textContent = '';
  input.classList.remove('is-invalid');

  const password = input.value;
  if (!password) {
    err.textContent = t('deleteAccountWrongPassword');
    input.classList.add('is-invalid');
    input.focus();
    return;
  }

  try {
    const res = await fetch('/api/delete-account', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      err.textContent = t('deleteAccountWrongPassword');
      input.classList.add('is-invalid');
      input.focus();
      return;
    }
    const confirmBtn = document.getElementById('btn-delete-confirm');
    confirmBtn.disabled = true;
    confirmBtn.classList.add('is-success');
    confirmBtn.textContent = t('deleteAccountSuccess');
    await new Promise(r => setTimeout(r, 500));
    closeAccountOptionsMenu();
    closeAccountManage();
    if (typeof clearPersistedViewSession === 'function') {
      clearPersistedViewSession();
    }
    await fadeTo('/login.html');
  } catch {
    err.textContent = t('deleteAccountWrongPassword');
    input.classList.add('is-invalid');
    input.focus();
  }
}