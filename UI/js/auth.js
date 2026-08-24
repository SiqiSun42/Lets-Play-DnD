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

function clearRegisterFieldErrors() {
  ['reg-username', 'reg-password', 'reg-confirm', 'reg-email'].forEach(id => {
    document.getElementById(`${id}-error`).textContent = '';
    document.getElementById(id).classList.remove('is-invalid');
  });
}

function validateRegisterForm() {
  clearRegisterFieldErrors();

  const username = document.getElementById('reg-username').value.trim();
  const password = document.getElementById('reg-password').value;
  const confirm = document.getElementById('reg-confirm').value;
  const email = document.getElementById('reg-email').value.trim();

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
  if (email && !EMAIL_RE.test(email)) {
    showFieldError('reg-email', 'reg-email-error', t('regInvalidEmail'));
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
          showFieldError('reg-email', 'reg-email-error', t('regEmailTaken'));
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
      <div class="auth-field-head">
        <div class="auth-label-with-help">
          <label for="reg-email">${t('email')}</label>
          <button type="button" class="auth-help" tabindex="-1">
            <svg class="auth-help-icon" viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">
              <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/>
              <path fill="currentColor" d="M12 17a1.2 1.2 0 1 1 0-2.4A1.2 1.2 0 0 1 12 17zm1-4.2h-2c0-1.7 1.6-1.9 1.6-3.1 0-.7-.5-1.2-1.3-1.2-.9 0-1.4.5-1.4 1.4H8.5C8.5 8.2 10 7 12.1 7c1.9 0 3.2 1.1 3.2 2.7 0 1.8-1.7 2.2-2.3 3.1z"/>
            </svg>
            <span class="auth-help-tip">${t('tipEmail')}</span>
          </button>
        </div>
        <span class="auth-field-error" id="reg-email-error"></span>
      </div>
      <input id="reg-email" name="email" type="text" placeholder="${t('emailPlaceholder')}" autocomplete="email">
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
    renderAuth();
  });
  bindRegisterForm();
  bindPasswordEyes();
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