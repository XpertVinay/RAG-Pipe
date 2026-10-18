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

    loginForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const u = document.getElementById('login-username').value.trim();
      const p = document.getElementById('login-password').value;
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
        RAG.utils.showToast(err.message, 'error');
      }
    });

    registerForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('reg-email').value.trim();
      const u = document.getElementById('reg-username').value.trim();
      const fn = document.getElementById('reg-fullname').value.trim();
      const p = document.getElementById('reg-password').value;
      try {
        RAG.utils.showToast('Creating account...', 'info');
        await API.register(email, u, p, fn);
        RAG.utils.showToast('Account created and signed in!', 'success');
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

    demoLoginBtn?.addEventListener('click', async () => {
      try {
        RAG.utils.showToast('Logging in with Demo Account...', 'info');
        try {
          await API.login('demo_user', 'demo123456');
        } catch {
          await API.register('demo@ragagent.local', 'demo_user', 'demo123456', 'Demo User');
        }
        RAG.utils.showToast('Demo User authenticated!', 'success');
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
