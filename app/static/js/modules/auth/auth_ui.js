/**
 * Authentication UI State Indicators, Tab Switcher & Token Viewer
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.auth = RAG.auth || {};

  function updateAuthUI() {
    const user = API.getCurrentUser();
    const accessToken = API.getAccessToken();
    const idToken = API.getIdToken();
    const refreshToken = API.getRefreshToken();

    const authUsernameLabel = document.getElementById('auth-username-label');
    const authAvatarLetter = document.getElementById('auth-avatar-letter');
    const authUserBtn = document.getElementById('auth-user-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const openOrgBtn = document.getElementById('open-org-btn');

    if (user && accessToken) {
      if (authUsernameLabel) authUsernameLabel.textContent = user.username || user.email;
      if (authAvatarLetter) authAvatarLetter.textContent = (user.username || user.email)[0].toUpperCase();
      if (authUserBtn) authUserBtn.title = `Signed in as ${user.email} (${user.role})`;
      if (logoutBtn) logoutBtn.style.display = 'inline-block';
    } else {
      if (authUsernameLabel) authUsernameLabel.textContent = 'Sign In';
      if (authAvatarLetter) authAvatarLetter.textContent = '👤';
      if (authUserBtn) authUserBtn.title = 'Click to Sign In or Register';
      if (logoutBtn) logoutBtn.style.display = 'none';
    }

    if (openOrgBtn) {
      openOrgBtn.style.display = user && accessToken && user.role === 'admin' ? 'inline-flex' : 'none';
    }

    const isAdminOrStaff = Boolean(user && accessToken && (user.role === 'admin' || user.role === 'staff' || user.role === 'staffs'));
    const tabBtnMemory = document.getElementById('tab-btn-memory');
    const panelMemory = document.getElementById('panel-memory');

    if (tabBtnMemory) {
      tabBtnMemory.style.display = isAdminOrStaff ? 'flex' : 'none';
    }

    if (!isAdminOrStaff) {
      if (tabBtnMemory?.classList.contains('active') || panelMemory?.classList.contains('active')) {
        if (window.switchSidebarTab) {
          window.switchSidebarTab('rooms');
        } else {
          document.getElementById('tab-btn-rooms')?.click();
        }
      }
    } else {
      if (API.getMemoryStats) {
        API.getMemoryStats()
          .then((stats) => {
            const tabMemoryBadge = document.getElementById('tab-memory-badge');
            if (tabMemoryBadge) tabMemoryBadge.textContent = stats.active_memories || stats.total_memories || 0;
          })
          .catch(() => {});
      }
    }

    const dropzoneHint = document.querySelector('.dropzone-hint');
    if (dropzoneHint) {
      if (user && accessToken) {
        dropzoneHint.innerHTML = 'Supports PDF, DOCX, TXT, MD, CSV, HTML (Max 25MB) • <span style="color: #10b981; font-weight: 500;">✓ Authenticated Uploader</span>';
      } else {
        dropzoneHint.innerHTML = 'Supports PDF, DOCX, TXT, MD, CSV, HTML • <span style="color: #f59e0b; font-weight: 500;">🔒 Sign in required to upload</span>';
      }
    }

    const rawAccessToken = document.getElementById('raw-access-token');
    const rawIdToken = document.getElementById('raw-id-token');
    const rawRefreshToken = document.getElementById('raw-refresh-token');
    const idTokenClaims = document.getElementById('id-token-claims');

    if (rawAccessToken) rawAccessToken.textContent = accessToken || 'None (Not signed in)';
    if (rawIdToken) rawIdToken.textContent = idToken || 'None (Not signed in)';
    if (rawRefreshToken) rawRefreshToken.textContent = refreshToken || 'None (Not signed in)';

    if (idToken && idTokenClaims) {
      const claims = RAG.utils.parseJwtPayload(idToken);
      if (claims) {
        idTokenClaims.innerHTML = Object.entries(claims)
          .map(([k, v]) => `<span class="token-claim-badge"><strong>${RAG.utils.escapeHtml(k)}:</strong> ${RAG.utils.escapeHtml(String(v))}</span>`)
          .join('');
      } else {
        idTokenClaims.innerHTML = '';
      }
    } else if (idTokenClaims) {
      idTokenClaims.innerHTML = '';
    }
  }

  function switchAuthTab(tabName) {
    const authTabSignin = document.getElementById('auth-tab-signin');
    const authTabRegister = document.getElementById('auth-tab-register');
    const authTabTokens = document.getElementById('auth-tab-tokens');
    const authPanelSignin = document.getElementById('auth-panel-signin');
    const authPanelRegister = document.getElementById('auth-panel-register');
    const authPanelTokens = document.getElementById('auth-panel-tokens');

    [authTabSignin, authTabRegister, authTabTokens].forEach((t) => t?.classList.remove('active'));
    [authPanelSignin, authPanelRegister, authPanelTokens].forEach((p) => {
      if (p) p.style.display = 'none';
    });

    ['login-username', 'login-password', 'reg-email', 'reg-username', 'reg-fullname', 'reg-password'].forEach((id) => {
      const el = document.getElementById(id);
      if (el && RAG.validator) RAG.validator.clearError(el);
    });

    if (tabName === 'signin') {
      authTabSignin?.classList.add('active');
      if (authPanelSignin) authPanelSignin.style.display = 'block';
    } else if (tabName === 'register') {
      authTabRegister?.classList.add('active');
      if (authPanelRegister) authPanelRegister.style.display = 'block';
    } else if (tabName === 'tokens') {
      authTabTokens?.classList.add('active');
      if (authPanelTokens) authPanelTokens.style.display = 'block';
      updateAuthUI();
    }
  }

  function copyToken(type) {
    let token = '';
    if (type === 'access') token = API.getAccessToken();
    else if (type === 'id') token = API.getIdToken();
    else if (type === 'refresh') token = API.getRefreshToken();

    if (!token) return RAG.utils.showToast('No token available to copy', 'error');
    navigator.clipboard.writeText(token).then(() => {
      RAG.utils.showToast(`${type.toUpperCase()} token copied to clipboard`, 'success');
    });
  }

  function showAuthModal(tab = 'signin', message = null) {
    switchAuthTab(tab);
    const authModal = document.getElementById('auth-modal');
    if (authModal) authModal.classList.add('active');
    if (message) {
      RAG.utils.showToast(message, 'warning');
    }
  }

  RAG.auth.updateAuthUI = updateAuthUI;
  RAG.auth.switchAuthTab = switchAuthTab;
  RAG.auth.copyToken = copyToken;
  RAG.auth.showAuthModal = showAuthModal;
})(window);
