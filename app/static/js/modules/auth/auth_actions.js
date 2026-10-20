/**
 * Authentication Action Handlers (Login, Registration, Demo Accounts, Logout State)
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.auth = RAG.auth || {};

  function handleLogoutState() {
    API.clearAuthSession();
    API.setActiveRoomId(null);
    localStorage.removeItem('rag_active_conv_id');

    try {
      const url = new URL(window.location);
      url.searchParams.delete('room');
      window.history.replaceState({}, '', url.pathname + (url.search ? url.search : ''));
    } catch {}

    RAG.state.currentRoomId = null;
    RAG.state.currentRoom = null;
    RAG.state.currentConversationId = null;
    RAG.state.activeDocuments = [];
    RAG.state.rooms = [];
    RAG.state.conversations = [];

    if (RAG.auth.updateAuthUI) RAG.auth.updateAuthUI();

    const bannerRoomName = document.getElementById('banner-room-name');
    if (bannerRoomName) bannerRoomName.textContent = 'Workspace';

    const bannerRoomFiles = document.getElementById('banner-room-files');
    if (bannerRoomFiles) bannerRoomFiles.innerHTML = '';

    const convTitle = document.getElementById('conv-title');
    if (convTitle) convTitle.textContent = 'Document Q&A Session';

    const convSubtitle = document.getElementById('conv-subtitle');
    if (convSubtitle) convSubtitle.textContent = 'Strictly grounded answers with verifiable source attribution';

    const refCountBadge = document.getElementById('ref-count-badge');
    if (refCountBadge) refCountBadge.textContent = '0';
    const refCardsGrid = document.getElementById('ref-cards-grid');
    if (refCardsGrid) refCardsGrid.innerHTML = '';
    const roomReferencesDrawer = document.getElementById('room-references-drawer');
    if (roomReferencesDrawer) roomReferencesDrawer.style.display = 'none';

    if (RAG.chat?.showWelcomeScreen) {
      RAG.chat.showWelcomeScreen();
    } else {
      const messagesContainer = document.getElementById('messages-container');
      if (messagesContainer) messagesContainer.innerHTML = '';
    }

    if (RAG.documents?.loadDocuments) RAG.documents.loadDocuments();
    if (RAG.rooms?.loadRooms) RAG.rooms.loadRooms();
    if (RAG.history?.loadConversations) RAG.history.loadConversations();
    if (RAG.memory?.loadMemoryDashboard) RAG.memory.loadMemoryDashboard();
  }

  async function handleLoginSubmit(e) {
    e.preventDefault();
    const loginUsernameInput = document.getElementById('login-username');
    const loginPasswordInput = document.getElementById('login-password');
    const authModal = document.getElementById('auth-modal');

    const u = loginUsernameInput?.value.trim() || '';
    const p = loginPasswordInput?.value || '';

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
      if (RAG.auth.updateAuthUI) RAG.auth.updateAuthUI();
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
  }

  async function handleRegisterSubmit(e) {
    e.preventDefault();
    const regEmailInput = document.getElementById('reg-email');
    const regUsernameInput = document.getElementById('reg-username');
    const regFullnameInput = document.getElementById('reg-fullname');
    const regPasswordInput = document.getElementById('reg-password');
    const authModal = document.getElementById('auth-modal');

    const email = regEmailInput?.value.trim() || '';
    const u = regUsernameInput?.value.trim() || '';
    const fn = regFullnameInput?.value.trim() || '';
    const p = regPasswordInput?.value || '';
    const role = document.getElementById('reg-role')?.value || 'user';

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
      await API.register(email, u, p, fn, role, window.activeInviteToken || null);
      const signedUser = API.getCurrentUser();
      const finalRole = signedUser?.role || role;
      const isMemPrivileged = signedUser && (signedUser.role === 'admin' || signedUser.role === 'staff' || signedUser.role === 'staffs');
      RAG.utils.showToast(`Account created successfully as ${finalRole}!`, 'success');
      authModal?.classList.remove('active');
      if (RAG.auth.updateAuthUI) RAG.auth.updateAuthUI();
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
  }

  RAG.auth.handleLogoutState = handleLogoutState;
  RAG.auth.handleLoginSubmit = handleLoginSubmit;
  RAG.auth.handleRegisterSubmit = handleRegisterSubmit;
})(window);
