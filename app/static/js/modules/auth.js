/**
 * Authentication, Registration, and JWT Token Inspector Module
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  function updateAuthUI() {
    const user = API.getCurrentUser();
    const accessToken = API.getAccessToken();
    const idToken = API.getIdToken();
    const refreshToken = API.getRefreshToken();

    const authUsernameLabel = document.getElementById('auth-username-label');
    const authAvatarLetter = document.getElementById('auth-avatar-letter');
    const authUserBtn = document.getElementById('auth-user-btn');
    const logoutBtn = document.getElementById('logout-btn');

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

    // Role-based visibility for Short & Long Term Memory (Admin & Staff only)
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
        API.getMemoryStats().then((stats) => {
          const tabMemoryBadge = document.getElementById('tab-memory-badge');
          if (tabMemoryBadge) tabMemoryBadge.textContent = stats.active_memories || stats.total_memories || 0;
        }).catch(() => {});
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

    // Populate Token Inspector
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
          .map(
            ([k, v]) =>
              `<span class="token-claim-badge"><strong>${RAG.utils.escapeHtml(k)}:</strong> ${RAG.utils.escapeHtml(String(v))}</span>`
          )
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

    // Clear previous field validation errors when switching tabs
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

  function handleLogoutState() {
    API.clearAuthSession();
    API.setActiveRoomId(null);
    localStorage.removeItem('rag_active_conv_id');

    // Clean URL query parameters (remove ?room=...)
    try {
      const url = new URL(window.location);
      url.searchParams.delete('room');
      window.history.replaceState({}, '', url.pathname + (url.search ? url.search : ''));
    } catch {}

    // Reset in-memory global state
    RAG.state.currentRoomId = null;
    RAG.state.currentRoom = null;
    RAG.state.currentConversationId = null;
    RAG.state.activeDocuments = [];
    RAG.state.rooms = [];
    RAG.state.conversations = [];

    // Update Auth UI indicators
    updateAuthUI();

    // Reset top banner room name & attached file pills
    const bannerRoomName = document.getElementById('banner-room-name');
    if (bannerRoomName) bannerRoomName.textContent = 'Workspace';

    const bannerRoomFiles = document.getElementById('banner-room-files');
    if (bannerRoomFiles) bannerRoomFiles.innerHTML = '';

    const convTitle = document.getElementById('conv-title');
    if (convTitle) convTitle.textContent = 'Document Q&A Session';

    const convSubtitle = document.getElementById('conv-subtitle');
    if (convSubtitle) convSubtitle.textContent = 'Strictly grounded answers with verifiable source attribution';

    // Reset database references
    const refCountBadge = document.getElementById('ref-count-badge');
    if (refCountBadge) refCountBadge.textContent = '0';
    const refCardsGrid = document.getElementById('ref-cards-grid');
    if (refCardsGrid) refCardsGrid.innerHTML = '';
    const roomReferencesDrawer = document.getElementById('room-references-drawer');
    if (roomReferencesDrawer) roomReferencesDrawer.style.display = 'none';

    // Reset Chat Messages view to Welcome / Sign-in prompt
    if (RAG.chat?.showWelcomeScreen) {
      RAG.chat.showWelcomeScreen();
    } else {
      const messagesContainer = document.getElementById('messages-container');
      if (messagesContainer) messagesContainer.innerHTML = '';
    }

    // Reload/Reset panels
    if (RAG.documents?.loadDocuments) RAG.documents.loadDocuments();
    if (RAG.rooms?.loadRooms) RAG.rooms.loadRooms();
    if (RAG.history?.loadConversations) RAG.history.loadConversations();
    if (RAG.memory?.loadMemoryDashboard) RAG.memory.loadMemoryDashboard();
  }

  function initAuthListeners() {
    const authTabSignin = document.getElementById('auth-tab-signin');
    const authTabRegister = document.getElementById('auth-tab-register');
    const authTabTokens = document.getElementById('auth-tab-tokens');
    const authUserBtn = document.getElementById('auth-user-btn');
    const authModal = document.getElementById('auth-modal');
    const closeAuthBtn = document.getElementById('close-auth-btn');
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    const demoLoginBtn = document.getElementById('demo-login-btn');
    const demoStaffBtn = document.getElementById('demo-staff-btn');
    const logoutBtn = document.getElementById('logout-btn');
    const refreshNowBtn = document.getElementById('refresh-now-btn');

    authTabSignin?.addEventListener('click', () => switchAuthTab('signin'));
    authTabRegister?.addEventListener('click', () => switchAuthTab('register'));
    authTabTokens?.addEventListener('click', () => switchAuthTab('tokens'));

    authUserBtn?.addEventListener('click', () => {
      const user = API.getCurrentUser();
      switchAuthTab(user ? 'tokens' : 'signin');
      authModal?.classList.add('active');
    });

    closeAuthBtn?.addEventListener('click', () => authModal?.classList.remove('active'));

    const loginUsernameInput = document.getElementById('login-username');
    const loginPasswordInput = document.getElementById('login-password');
    const regEmailInput = document.getElementById('reg-email');
    const regUsernameInput = document.getElementById('reg-username');
    const regFullnameInput = document.getElementById('reg-fullname');
    const regPasswordInput = document.getElementById('reg-password');

    // Attach live interactive validation
    if (RAG.validator) {
      if (loginUsernameInput) RAG.validator.attachLiveValidation(loginUsernameInput, RAG.validator.validateLoginIdentifier);
      if (loginPasswordInput) RAG.validator.attachLiveValidation(loginPasswordInput, (val) => RAG.validator.validatePassword(val, 6));
      if (regEmailInput) RAG.validator.attachLiveValidation(regEmailInput, RAG.validator.validateEmail);
      if (regUsernameInput) RAG.validator.attachLiveValidation(regUsernameInput, RAG.validator.validateUsername);
      if (regFullnameInput) RAG.validator.attachLiveValidation(regFullnameInput, RAG.validator.validateFullName);
      if (regPasswordInput) RAG.validator.attachLiveValidation(regPasswordInput, (val) => RAG.validator.validatePassword(val, 6));
    }

    loginForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const u = loginUsernameInput?.value.trim() || '';
      const p = loginPasswordInput?.value || '';

      // JavaScript Input Validation
      if (RAG.validator) {
        const uErr = RAG.validator.validateLoginIdentifier(u);
        if (uErr) {
          RAG.validator.showError(loginUsernameInput, uErr);
          loginUsernameInput?.focus();
          return;
        } else {
          RAG.validator.clearError(loginUsernameInput);
        }

        const pErr = RAG.validator.validatePassword(p, 6);
        if (pErr) {
          RAG.validator.showError(loginPasswordInput, pErr);
          loginPasswordInput?.focus();
          return;
        } else {
          RAG.validator.clearError(loginPasswordInput);
        }
      }

      try {
        RAG.utils.showToast('Authenticating...', 'info');
        await API.login(u, p);
        RAG.utils.showToast('Successfully signed in!', 'success');
        authModal?.classList.remove('active');
        updateAuthUI();
        if (RAG.rooms?.loadRooms) RAG.rooms.loadRooms();
        if (RAG.documents?.loadDocuments) RAG.documents.loadDocuments();
        if (RAG.history?.loadConversations) RAG.history.loadConversations();
        if (RAG.memory?.loadMemoryDashboard) RAG.memory.loadMemoryDashboard();
        if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
      } catch (err) {
        if (loginPasswordInput && RAG.validator) {
          RAG.validator.showError(loginPasswordInput, err.message);
        }
        RAG.utils.showToast(err.message, 'error');
      }
    });

    registerForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = regEmailInput?.value.trim() || '';
      const u = regUsernameInput?.value.trim() || '';
      const fn = regFullnameInput?.value.trim() || '';
      const p = regPasswordInput?.value || '';
      const role = document.getElementById('reg-role')?.value || 'user';

      // JavaScript Input Validation
      if (RAG.validator) {
        const emailErr = RAG.validator.validateEmail(email);
        if (emailErr) {
          RAG.validator.showError(regEmailInput, emailErr);
          regEmailInput?.focus();
          return;
        } else {
          RAG.validator.clearError(regEmailInput);
        }

        const uErr = RAG.validator.validateUsername(u);
        if (uErr) {
          RAG.validator.showError(regUsernameInput, uErr);
          regUsernameInput?.focus();
          return;
        } else {
          RAG.validator.clearError(regUsernameInput);
        }

        const fnErr = RAG.validator.validateFullName(fn);
        if (fnErr) {
          RAG.validator.showError(regFullnameInput, fnErr);
          regFullnameInput?.focus();
          return;
        } else {
          RAG.validator.clearError(regFullnameInput);
        }

        const pErr = RAG.validator.validatePassword(p, 6);
        if (pErr) {
          RAG.validator.showError(regPasswordInput, pErr);
          regPasswordInput?.focus();
          return;
        } else {
          RAG.validator.clearError(regPasswordInput);
        }
      }

      try {
        RAG.utils.showToast('Creating account...', 'info');
        await API.register(email, u, p, fn, role);
        const signedUser = API.getCurrentUser();
        const isMemPrivileged = signedUser && (signedUser.role === 'admin' || signedUser.role === 'staff' || signedUser.role === 'staffs');
        RAG.utils.showToast(`Account created as ${role}!`, 'success');
        authModal?.classList.remove('active');
        updateAuthUI();
        if (RAG.rooms?.loadRooms) RAG.rooms.loadRooms();
        if (RAG.documents?.loadDocuments) RAG.documents.loadDocuments();
        if (RAG.history?.loadConversations) RAG.history.loadConversations();
        if (isMemPrivileged && RAG.memory?.loadMemoryDashboard) RAG.memory.loadMemoryDashboard();
        if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
      } catch (err) {
        if (regUsernameInput && RAG.validator) {
          RAG.validator.showError(regUsernameInput, err.message);
        }
        RAG.utils.showToast(err.message, 'error');
      }
    });

    demoLoginBtn?.addEventListener('click', async () => {
      try {
        RAG.utils.showToast('Logging in with Demo Account...', 'info');
        try {
          await API.login('demo_user', 'demo123456');
        } catch {
          await API.register('demo@ragagent.local', 'demo_user', 'demo123456', 'Demo User', 'user');
        }
        RAG.utils.showToast('Demo User authenticated (Standard access)!', 'success');
        authModal?.classList.remove('active');
        updateAuthUI();
        if (RAG.rooms?.loadRooms) RAG.rooms.loadRooms();
        if (RAG.documents?.loadDocuments) RAG.documents.loadDocuments();
        if (RAG.history?.loadConversations) RAG.history.loadConversations();
        if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
      } catch (err) {
        RAG.utils.showToast(err.message, 'error');
      }
    });

    demoStaffBtn?.addEventListener('click', async () => {
      try {
        RAG.utils.showToast('Logging in with Demo Staff Account...', 'info');
        try {
          await API.login('staff_demo', 'staff123456');
        } catch {
          await API.register('staff@ragagent.local', 'staff_demo', 'staff123456', 'Demo Staff', 'staff');
        }
        RAG.utils.showToast('Demo Staff authenticated (Memory access enabled)!', 'success');
        authModal?.classList.remove('active');
        updateAuthUI();
        if (RAG.rooms?.loadRooms) RAG.rooms.loadRooms();
        if (RAG.documents?.loadDocuments) RAG.documents.loadDocuments();
        if (RAG.history?.loadConversations) RAG.history.loadConversations();
        if (RAG.memory?.loadMemoryDashboard) RAG.memory.loadMemoryDashboard();
        if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
      } catch (err) {
        RAG.utils.showToast(err.message, 'error');
      }
    });

    logoutBtn?.addEventListener('click', async () => {
      await API.logout();
      RAG.utils.showToast('Signed out', 'info');
      authModal?.classList.remove('active');
      handleLogoutState();
    });

    refreshNowBtn?.addEventListener('click', async () => {
      RAG.utils.showToast('Refreshing tokens...', 'info');
      const success = await API.refreshAuth();
      if (success) {
        RAG.utils.showToast('Tokens successfully refreshed & rotated!', 'success');
        updateAuthUI();
      } else {
        RAG.utils.showToast('Failed to refresh tokens. Please log in again.', 'error');
      }
    });
  }

  RAG.auth = {
    updateAuthUI,
    switchAuthTab,
    showAuthModal,
    handleLogoutState,
    copyToken,
    init: initAuthListeners,
  };

  global.updateAuthUI = updateAuthUI;
  global.switchAuthTab = switchAuthTab;
  global.showAuthModal = showAuthModal;
  global.handleLogoutState = handleLogoutState;
  global.copyToken = copyToken;
})(window);
