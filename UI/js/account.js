let currentAccount = null;

function getLoggedInAccount() {
  return currentAccount;
}

function getCurrentAccount() {
  return currentAccount;
}

function getAccountSettingsPath(account) {
  return `Account/${account}/settings.json`;
}

async function fetchJSON(path) {
  const res = await fetch(path, { cache: 'no-store' });
  if (!res.ok) {
    throw new Error(`Failed to load ${path}: ${res.status}`);
  }
  return res.json();
}

async function fetchMe() {
  const res = await fetch('api/me', { cache: 'no-store' });
  if (!res.ok) {
    return null;
  }
  const data = await res.json();
  return data.user;
}

async function logoutAccount() {
  await fetch('api/logout', { method: 'POST' });
  currentAccount = null;
}

function getAccountFilePath(relativePath) {
  return `Account/${getCurrentAccount()}/${relativePath}`;
}

async function patchFile(relativePath, patch) {
  const res = await fetch('api/patch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      path: getAccountFilePath(relativePath),
      patch
    })
  });
  if (!res.ok) {
    throw new Error(`patch failed: ${res.status}`);
  }
  return res.json();
}

async function initAccount() {
  const user = await fetchMe();
  if (!user) {
    throw new Error('not logged in');
  }

  currentAccount = user.username;
  const settings = await fetchJSON(getAccountSettingsPath(user.username));
  return { account: user.username, settings, user };
}

function applyAccountSettings(settings) {
    document.documentElement.lang = settings.language;
    document.documentElement.setAttribute('data-color-theme', settings.theme);
  
    const label = document.getElementById('account-label');
    const avatar = document.getElementById('avatar');
    if (label) label.textContent = getCurrentAccount();
    if (avatar) avatar.textContent = getCurrentAccount().charAt(0);
  }