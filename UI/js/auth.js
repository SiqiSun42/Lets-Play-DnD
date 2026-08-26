let authMode = 'login';

function bindLangToggle() {
  const btn = document.getElementById('btn-switch-lang');
  btn.addEventListener('click', () => {
    const current = localStorage.getItem('app-language') || 'zh-CN';
    const next = current === 'zh-CN' ? 'en' : 'zh-CN';
    localStorage.setItem('app-language', next);
    document.documentElement.lang = next;
    btn.classList.toggle('is-en', next === 'en');

    btn.addEventListener('transitionend', function onEnd(e) {
      if (e.propertyName !== 'transform') return;
      btn.removeEventListener('transitionend', onEnd);
      renderAuth();
    });
  });
}

function clearFieldErrors() {
  document.getElementById('auth-login-error').textContent = '';
  document.getElementById('auth-password-error').textContent = '';
  document.getElementById('auth-login').classList.remove('is-invalid');
  document.getElementById('auth-password').classList.remove('is-invalid');
}

function showFieldError(inputId, errorId, message) {
  const input = document.getElementById(inputId);
  document.getElementById(errorId).textContent = message;
  input.classList.add('is-invalid');
  input.focus();
}

function bindLoginForm() {
  const form = document.getElementById('auth-form');

  form.addEventListener('submit', async e => {
    e.preventDefault();
    clearFieldErrors();

    const loginInput = document.getElementById('auth-login');
    const passwordInput = document.getElementById('auth-password');
    const login = loginInput.value.trim();
    const password = passwordInput.value;

    if (!login) {
      showFieldError('auth-login', 'auth-login-error', t('loginMissingAccount'));
      return;
    }
    if (!password) {
      showFieldError('auth-password', 'auth-password-error', t('loginMissingPassword'));
      return;
    }

    try {
      const remember = document.getElementById('auth-remember').checked;
      const res = await fetch('api/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login, password, remember }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (data.error === 'user_not_found') {
          showFieldError('auth-login', 'auth-login-error', t('loginUserNotFound'));
        } else {
          showFieldError('auth-password', 'auth-password-error', t('loginPasswordIncorrect'));
        }
        return;
      }
      const language = localStorage.getItem('app-language') || 'zh-CN';
      await fetch('api/patch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: `Account/${data.user.username}/settings.json`,
          patch: { language },
        }),
      });
      await fetch('api/meta/patch-by-id', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: 'consult',
          patch: { in_game_language: language },
        }),
      });
      const submitBtn = form.querySelector('.auth-submit');
      submitBtn.disabled = true;
      submitBtn.classList.add('is-success');
      submitBtn.textContent = t('loginSuccess');
      setTimeout(() => {
        window.location.href = './';
      }, 500);
    } catch {
      showFieldError('auth-password', 'auth-password-error', t('loginPasswordIncorrect'));
    }
  });
}

const USERNAME_RE = /^[A-Za-z][A-Za-z0-9_-]{2,31}$/;
const PASSWORD_RE = /^[A-Za-z0-9_]{6,64}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

let registerVerifiedEmail = '';

function syncRegEmailStatusRow() {
  const valueEl = document.getElementById('reg-email-status');
  const btn = document.getElementById('btn-reg-verify-email');
  if (!valueEl || !btn) return;
  const bound = !!registerVerifiedEmail;
  valueEl.textContent = bound ? t('emailBound') : t('emailNotBound');
  btn.disabled = false;
  btn.textContent = t('verifyEmail');
}

function clearRegModalEmailError() {
  const err = document.getElementById('reg-modal-email-error');
  const input = document.getElementById('reg-modal-email');
  if (err) err.textContent = '';
  if (input) input.classList.remove('is-invalid');
}

function showRegModalEmailError(message) {
  const err = document.getElementById('reg-modal-email-error');
  const input = document.getElementById('reg-modal-email');
  if (err) err.textContent = message;
  if (input) {
    input.classList.add('is-invalid');
    input.focus();
  }
}

function clearRegModalCodeError() {
  const err = document.getElementById('reg-modal-code-error');
  const input = document.getElementById('reg-modal-code');
  if (err) err.textContent = '';
  if (input) input.classList.remove('is-invalid');
}

function showRegModalCodeError(message) {
  const err = document.getElementById('reg-modal-code-error');
  const input = document.getElementById('reg-modal-code');
  if (err) err.textContent = message;
  if (input) {
    input.classList.add('is-invalid');
    input.focus();
  }
}

function normalizeRegEmailCode(raw) {
  return String(raw || '').replace(/\D/g, '');
}

let regEmailCodeCooldownTimer = null;

function stopRegEmailCodeCooldown() {
  if (regEmailCodeCooldownTimer) {
    clearInterval(regEmailCodeCooldownTimer);
    regEmailCodeCooldownTimer = null;
  }
}

function startRegEmailCodeCooldown(seconds) {
  stopRegEmailCodeCooldown();
  const sendBtn = document.getElementById('btn-reg-modal-send-code');
  if (!sendBtn) return;

  let left = seconds;
  sendBtn.disabled = true;
  sendBtn.classList.remove('is-success');
  sendBtn.textContent = `${t('resendVerificationCode')} ${left}s`;

  regEmailCodeCooldownTimer = setInterval(() => {
    left -= 1;
    const btn = document.getElementById('btn-reg-modal-send-code');
    if (!btn) {
      stopRegEmailCodeCooldown();
      return;
    }
    if (left <= 0) {
      stopRegEmailCodeCooldown();
      btn.disabled = false;
      btn.textContent = t('resendVerificationCode');
      return;
    }
    btn.textContent = `${t('resendVerificationCode')} ${left}s`;
  }, 1000);
}

function closeRegEmailModal() {
  stopRegEmailCodeCooldown();
  const modal = document.getElementById('reg-email-modal');
  if (modal) modal.classList.add('hidden');
}

function openRegEmailModal() {
  const modal = document.getElementById('reg-email-modal');
  const title = document.getElementById('reg-email-modal-title');
  const body = document.getElementById('reg-email-modal-body');
  if (!modal || !title || !body) return;

  title.textContent = t('verifyEmailTitle');
  body.innerHTML = `
    <form class="auth-modal-form" id="reg-email-verify-form">
      <div class="auth-modal-field">
        <div class="auth-modal-field-head">
          <div class="auth-modal-label-with-help">
            <label for="reg-modal-email">${t('newEmail')}</label>
            <button type="button" class="auth-modal-help" tabindex="-1">
              <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>
                <path fill="currentColor" d="M12 17a1.2 1.2 0 1 1 0-2.4A1.2 1.2 0 0 1 12 17zm1-4.2h-2c0-1.7 1.6-1.9 1.6-3.1 0-.7-.5-1.2-1.3-1.2-.9 0-1.4.5-1.4 1.4H8.5C8.5 8.2 10 7 12.1 7c1.9 0 3.2 1.1 3.2 2.7 0 1.8-1.7 2.2-2.3 3.1z"/>
              </svg>
              <span class="auth-modal-help-tip">${t('tipVerifyEmail')}</span>
            </button>
          </div>
          <span class="auth-modal-field-error" id="reg-modal-email-error"></span>
        </div>
        <input id="reg-modal-email" type="text" placeholder="${t('newEmailPlaceholder')}" autocomplete="email">
      </div>
      <div class="auth-modal-field">
        <div class="auth-modal-field-head">
          <div class="auth-modal-label-with-help">
            <label for="reg-modal-code">${t('verificationCode')}</label>
          </div>
          <span class="auth-modal-field-error" id="reg-modal-code-error"></span>
        </div>
        <div class="auth-modal-code-row">
          <input id="reg-modal-code" type="text" inputmode="numeric" autocomplete="one-time-code" placeholder="${t('verificationCodePlaceholder')}" maxlength="7">
          <button type="button" class="auth-modal-btn auth-modal-btn-primary auth-modal-send" id="btn-reg-modal-send-code">${t('sendVerificationCode')}</button>
        </div>
      </div>
      <div class="auth-modal-actions">
        <button type="button" class="auth-modal-btn" id="btn-reg-modal-back">${t('back')}</button>
        <button type="submit" class="auth-modal-btn auth-modal-btn-primary" id="btn-reg-modal-save">${t('savePassword')}</button>
      </div>
    </form>
  `;

  if (registerVerifiedEmail) {
    document.getElementById('reg-modal-email').value = registerVerifiedEmail;
  }

  document.getElementById('btn-reg-modal-back').addEventListener('click', closeRegEmailModal);
  document.getElementById('btn-reg-modal-send-code').addEventListener('click', onRegModalSendCode);
  document.getElementById('reg-email-verify-form').addEventListener('submit', onRegModalSave);

  modal.classList.remove('hidden');
}

function applyRegisterEmailBound(email) {
  registerVerifiedEmail = (email || '').trim();
  closeRegEmailModal();
  syncRegEmailStatusRow();
}

async function onRegModalSendCode() {
  clearRegModalEmailError();
  clearRegModalCodeError();
  const email = document.getElementById('reg-modal-email').value.trim();
  if (!email) {
    showRegModalEmailError(t('emailMissing'));
    return;
  }
  if (!EMAIL_RE.test(email) || email.endsWith('@local.invalid')) {
    showRegModalEmailError(t('emailInvalid'));
    return;
  }

  const sendBtn = document.getElementById('btn-reg-modal-send-code');
  if (sendBtn.disabled) return;
  sendBtn.disabled = true;
  try {
    const res = await fetch('api/register/send-code', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (data.error === 'email_taken') {
        showRegModalEmailError(t('emailTaken'));
      } else if (data.error === 'missing_email') {
        showRegModalEmailError(t('emailMissing'));
      } else if (data.error === 'too_fast') {
        const wait = Math.max(1, Number(data.retry_after) || 60);
        startRegEmailCodeCooldown(wait);
        return;
      } else {
        showRegModalEmailError(t('emailInvalid'));
      }
      sendBtn.disabled = false;
      return;
    }
    startRegEmailCodeCooldown(60);
  } catch {
    showRegModalEmailError(t('emailInvalid'));
    sendBtn.disabled = false;
  }
}

async function onRegModalSave(e) {
  e.preventDefault();
  clearRegModalEmailError();
  clearRegModalCodeError();

  const email = document.getElementById('reg-modal-email').value.trim();
  const code = normalizeRegEmailCode(document.getElementById('reg-modal-code').value);

  if (!code) {
    showRegModalCodeError(t('codeMissing'));
    return;
  }

  const saveBtn = document.getElementById('btn-reg-modal-save');
  try {
    const res = await fetch('api/register/verify-email', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, code }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showRegModalCodeError(t('codeMismatch'));
      return;
    }
    saveBtn.disabled = true;
    saveBtn.classList.add('is-success');
    saveBtn.textContent = t('emailChangeSuccess');
    setTimeout(() => {
      applyRegisterEmailBound(data.email || email);
    }, 500);
  } catch {
    showRegModalCodeError(t('codeMismatch'));
  }
}

function bindRegEmailModalOnce() {
  const modal = document.getElementById('reg-email-modal');
  if (!modal || modal.dataset.bound === '1') return;
  modal.dataset.bound = '1';
  modal.addEventListener('click', e => {
    if (e.target === modal) closeRegEmailModal();
  });
}

function clearRegisterFieldErrors() {
  ['reg-username', 'reg-password', 'reg-confirm'].forEach(id => {
    const err = document.getElementById(`${id}-error`);
    const input = document.getElementById(id);
    if (err) err.textContent = '';
    if (input) input.classList.remove('is-invalid');
  });
  const emailErr = document.getElementById('reg-email-error');
  if (emailErr) emailErr.textContent = '';
}

function validateRegisterForm() {
  clearRegisterFieldErrors();

  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value;
  const confirm = document.getElementById('reg-confirm').value;
  const email = registerVerifiedEmail;

  if (!username) {
    showFieldError('reg-username', 'reg-username-error', t('regMissingUsername'));
    return null;
  }
  if (!USERNAME_RE.test(username)) {
    showFieldError('reg-username', 'reg-username-error', t('regInvalidUsername'));
    return null;
  }
  if (!password) {
    showFieldError('reg-password', 'reg-password-error', t('regMissingPassword'));
    return null;
  }
  if (!PASSWORD_RE.test(password)) {
    showFieldError('reg-password', 'reg-password-error', t('regInvalidPassword'));
    return null;
  }
  if (!confirm) {
    showFieldError('reg-confirm', 'reg-confirm-error', t('regMissingConfirm'));
    return null;
  }
  if (password !== confirm) {
    showFieldError('reg-confirm', 'reg-confirm-error', t('regPasswordMismatch'));
    return null;
  }

  return { username, password, email };
}

function bindRegisterForm() {
  const form = document.getElementById('auth-form');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const data = validateRegisterForm();
    if (!data) return;

    try {
      const language = localStorage.getItem('app-language') || 'zh-CN';
      const res = await fetch('api/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: data.username,
          password: data.password,
          email: data.email,
          language,
        }),
      });
      const result = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (result.error === 'username_taken') {
          showFieldError('reg-username', 'reg-username-error', t('regUsernameTaken'));
        } else if (result.error === 'email_taken') {
          const emailErr = document.getElementById('reg-email-error');
          if (emailErr) emailErr.textContent = t('regEmailTaken');
        } else if (result.error === 'email_not_verified') {
          const emailErr = document.getElementById('reg-email-error');
          if (emailErr) emailErr.textContent = t('emailNotVerified');
        } else {
          showFieldError('reg-username', 'reg-username-error', t('regUsernameTaken'));
        }
        return;
      }
      const submitBtn = form.querySelector('.auth-submit');
      submitBtn.disabled = true;
      submitBtn.classList.add('is-success');
      submitBtn.textContent = t('regSuccess');
      setTimeout(() => {
        authMode = 'login';
        registerVerifiedEmail = '';
        renderAuth();
      }, 500);
    } catch {
      showFieldError('reg-username', 'reg-username-error', t('regUsernameTaken'));
    }
  });
}

function eyeClosedSvg() {
  return `
    <svg class="auth-eye-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path fill="currentColor" d="M12 5c-5 0-9.3 3.1-11 7 1.7 3.9 6 7 11 7s9.3-3.1 11-7c-1.7-3.9-6-7-11-7zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/>
      <path fill="currentColor" d="M3.3 3.3 20.7 20.7l-1.4 1.4L1.9 4.7z"/>
    </svg>
  `;
}

function eyeOpenSvg() {
  return `
    <svg class="auth-eye-icon" viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
      <path fill="currentColor" d="M12 5c-5 0-9.3 3.1-11 7 1.7 3.9 6 7 11 7s9.3-3.1 11-7c-1.7-3.9-6-7-11-7zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-2.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z"/>
    </svg>
  `;
}

function bindPasswordEyes() {
  document.querySelectorAll('.auth-eye').forEach(btn => {
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

function renderLoginForm() {
  const card = document.getElementById('auth-card');
  const lang = localStorage.getItem('app-language') || 'zh-CN';

  card.innerHTML = `
    <form class="auth-form" id="auth-form">
      <div class="auth-field">
        <div class="auth-field-head">
          <label for="auth-login">${t('loginOrEmail')}</label>
          <span class="auth-field-error" id="auth-login-error"></span>
        </div>
        <input id="auth-login" name="login" type="text" placeholder="${t('loginOrEmailPlaceholder')}" autocomplete="username">
      </div>
      <div class="auth-field">
        <div class="auth-field-head">
          <label for="auth-password">${t('password')}</label>
          <span class="auth-field-error" id="auth-password-error"></span>
        </div>
        <div class="auth-password-wrap">
          <input id="auth-password" name="password" type="password" placeholder="${t('passwordPlaceholder')}" autocomplete="current-password">
          <button type="button" class="auth-eye" data-eye-for="auth-password" aria-label="show password">${eyeClosedSvg()}</button>
        </div>
      </div>
      <div class="auth-row">
        <label class="auth-remember">
          <input type="checkbox" id="auth-remember" name="remember">
          <span>${t('rememberLogin')}</span>
        </label>
        <button type="button" class="auth-link" id="btn-forgot-password">${t('forgotPassword')}</button>
      </div>
      <button type="submit" class="auth-submit">${t('login')}</button>
      <div class="auth-footer">
        <button type="button" class="auth-footer-btn" id="btn-create-account">${t('createAccount')}</button>
        <span class="auth-footer-divider" aria-hidden="true"></span>
        <button type="button" class="lang-toggle${lang === 'en' ? ' is-en' : ''}" id="btn-switch-lang" aria-label="${t('switchLanguage')}">
          <span class="lang-toggle-knob"></span>
          <span class="lang-toggle-label lang-toggle-zh">文</span>
          <span class="lang-toggle-label lang-toggle-en">A</span>
        </button>
      </div>
    </form>
  `;

  bindLangToggle();
  bindLoginForm();
  bindPasswordEyes();

  document.getElementById('btn-create-account').addEventListener('click', () => {
    authMode = 'register';
    renderAuth();
  });
}

function renderRegisterForm() {
  const card = document.getElementById('auth-card');
  const lang = localStorage.getItem('app-language') || 'zh-CN';

  card.innerHTML = `
    <form class="auth-form" id="auth-form">
    <div class="auth-field">
      <div class="auth-field-head">
        <div class="auth-label-with-help">
          <label for="reg-username">${t('username')}</label>
          <button type="button" class="auth-help" tabindex="-1">
            <svg class="auth-help-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
              <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>
              <path fill="currentColor" d="M12 17a1.2 1.2 0 1 1 0-2.4A1.2 1.2 0 0 1 12 17zm1-4.2h-2c0-1.7 1.6-1.9 1.6-3.1 0-.7-.5-1.2-1.3-1.2-.9 0-1.4.5-1.4 1.4H8.5C8.5 8.2 10 7 12.1 7c1.9 0 3.2 1.1 3.2 2.7 0 1.8-1.7 2.2-2.3 3.1z"/>
            </svg>
            <span class="auth-help-tip">${t('tipUsername')}</span>
          </button>
        </div>
        <span class="auth-field-error" id="reg-username-error"></span>
      </div>
      <input id="reg-username" name="username" type="text" placeholder="${t('usernamePlaceholder')}" autocomplete="username">
    </div>
      <div class="auth-field">
        <div class="auth-field-head">
          <div class="auth-label-with-help">
            <label for="reg-password">${t('password')}</label>
            <button type="button" class="auth-help" tabindex="-1">
              <svg class="auth-help-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>
                <path fill="currentColor" d="M12 17a1.2 1.2 0 1 1 0-2.4A1.2 1.2 0 0 1 12 17zm1-4.2h-2c0-1.7 1.6-1.9 1.6-3.1 0-.7-.5-1.2-1.3-1.2-.9 0-1.4.5-1.4 1.4H8.5C8.5 8.2 10 7 12.1 7c1.9 0 3.2 1.1 3.2 2.7 0 1.8-1.7 2.2-2.3 3.1z"/>
              </svg>
              <span class="auth-help-tip">${t('tipPassword')}</span>
            </button>
          </div>
          <span class="auth-field-error" id="reg-password-error"></span>
        </div>
        <div class="auth-password-wrap">
          <input id="reg-password" name="password" type="password" placeholder="${t('passwordPlaceholder')}" autocomplete="new-password">
          <button type="button" class="auth-eye" data-eye-for="reg-password" aria-label="show password">${eyeClosedSvg()}</button>
        </div>
      </div>
      <div class="auth-field">
        <div class="auth-field-head">
          <label for="reg-confirm">${t('confirmPassword')}</label>
          <span class="auth-field-error" id="reg-confirm-error"></span>
        </div>
        <div class="auth-password-wrap">
          <input id="reg-confirm" name="confirm" type="password" placeholder="${t('confirmPasswordPlaceholder')}" autocomplete="new-password">
          <button type="button" class="auth-eye" data-eye-for="reg-confirm" aria-label="show password">${eyeClosedSvg()}</button>
        </div>
      </div>
      <div class="auth-field">
        <div class="auth-email-status-row">
          <div class="auth-email-status-left">
            <span>${t('email')}:</span>
            <span class="auth-email-status-value" id="reg-email-status">${registerVerifiedEmail ? t('emailBound') : t('emailNotBound')}</span>
          </div>
          <button type="button" class="auth-email-verify-btn" id="btn-reg-verify-email">${t('verifyEmail')}</button>
        </div>
        <span class="auth-field-error" id="reg-email-error"></span>
      </div>
      <button type="submit" class="auth-submit">${t('createUser')}</button>
      <div class="auth-footer">
        <button type="button" class="auth-footer-btn" id="btn-back-login">${t('backToLogin')}</button>
        <span class="auth-footer-divider" aria-hidden="true"></span>
        <button type="button" class="lang-toggle${lang === 'en' ? ' is-en' : ''}" id="btn-switch-lang" aria-label="${t('switchLanguage')}">
          <span class="lang-toggle-knob"></span>
          <span class="lang-toggle-label lang-toggle-zh">文</span>
          <span class="lang-toggle-label lang-toggle-en">A</span>
        </button>
      </div>
    </form>
  `;

  bindLangToggle();
  document.getElementById('btn-back-login').addEventListener('click', () => {
    authMode = 'login';
    registerVerifiedEmail = '';
    renderAuth();
  });
  bindRegisterForm();
  bindPasswordEyes();
  bindRegEmailModalOnce();
  syncRegEmailStatusRow();
  document.getElementById('btn-reg-verify-email').addEventListener('click', openRegEmailModal);
}

function renderAuth() {
  const title = document.querySelector('.auth-title');
  if (title) {
    title.classList.toggle('hidden', authMode === 'register');
  }
  if (authMode === 'register') renderRegisterForm();
  else renderLoginForm();
}

document.documentElement.lang = localStorage.getItem('app-language') || 'zh-CN';
renderAuth();