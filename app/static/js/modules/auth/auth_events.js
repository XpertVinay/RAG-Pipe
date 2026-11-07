/**
 * Authentication DOM Event Listeners, Demo Sign-in & Refresh Buttons
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.auth = RAG.auth || {};

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

    authTabSignin?.addEventListener('click', () => RAG.auth.switchAuthTab && RAG.auth.switchAuthTab('signin'));
    authTabRegister?.addEventListener('click', () => RAG.auth.switchAuthTab && RAG.auth.switchAuthTab('register'));
    authTabTokens?.addEventListener('click', () => RAG.auth.switchAuthTab && RAG.auth.switchAuthTab('tokens'));

    // Profile Dropdown Elements
    const profileDropdownContainer = document.getElementById('profileDropdownContainer');
    const profileDropdownMenu = document.getElementById('profileDropdownMenu');
    const profileMenuTokensBtn = document.getElementById('profile-menu-tokens-btn');
    const profileMenuSettingsBtn = document.getElementById('profile-menu-settings-btn');
    const profileMenuLogoutBtn = document.getElementById('profile-menu-logout-btn');
    const openSettingsBtn = document.getElementById('open-settings-btn');

    function closeProfileMenu() {
      if (profileDropdownMenu?.classList.contains('show')) {
        profileDropdownMenu.classList.remove('show');
        authUserBtn?.setAttribute('aria-expanded', 'false');
      }
    }

    function toggleProfileMenu() {
      const isOpen = profileDropdownMenu?.classList.contains('show');
      // Close theme or room menus if open
      document.querySelectorAll('.theme-menu.show').forEach((m) => {
        m.classList.remove('show');
        const b = m.closest('.theme-dropdown-container')?.querySelector('.theme-toggle-btn');
        if (b) b.setAttribute('aria-expanded', 'false');
      });
      document.querySelectorAll('.room-dropdown-menu.show').forEach((m) => {
        m.classList.remove('show');
        const b = document.getElementById('room-dropdown-btn');
        if (b) b.setAttribute('aria-expanded', 'false');
      });

      if (isOpen) {
        closeProfileMenu();
      } else {
        profileDropdownMenu?.classList.add('show');
        authUserBtn?.setAttribute('aria-expanded', 'true');
      }
    }

    // Toggle dropdown on profile button click
    authUserBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleProfileMenu();
    });

    // Account & Tokens option in profile dropdown
    profileMenuTokensBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeProfileMenu();
      const user = API.getCurrentUser();
      if (RAG.auth.switchAuthTab) RAG.auth.switchAuthTab(user ? 'tokens' : 'signin');
      authModal?.classList.add('active');
    });

    // Settings shortcut in profile dropdown
    profileMenuSettingsBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeProfileMenu();
      openSettingsBtn?.click();
    });

    // Sign out / Sign in button in profile dropdown
    profileMenuLogoutBtn?.addEventListener('click', async (e) => {
      e.preventDefault();
      e.stopPropagation();
      closeProfileMenu();
      const user = API.getCurrentUser();
      const accessToken = API.getAccessToken();
      if (user && accessToken) {
        await API.logout();
        RAG.utils.showToast('Signed out', 'info');
        authModal?.classList.remove('active');
        if (RAG.auth.handleLogoutState) RAG.auth.handleLogoutState();
      } else {
        if (RAG.auth.switchAuthTab) RAG.auth.switchAuthTab('signin');
        authModal?.classList.add('active');
      }
    });

    // Auto-close profile menu when any profile menu item is clicked
    profileDropdownMenu?.addEventListener('click', (e) => {
      const item = e.target.closest('.profile-menu-item');
      if (item && item !== profileMenuTokensBtn && item !== profileMenuSettingsBtn && item !== profileMenuLogoutBtn) {
        closeProfileMenu();
      }
    });

    // Close when clicking outside
    document.addEventListener('click', (e) => {
      if (!profileDropdownContainer?.contains(e.target)) {
        closeProfileMenu();
      }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeProfileMenu();
      }
    });

    closeAuthBtn?.addEventListener('click', () => authModal?.classList.remove('active'));

    const loginUsernameInput = document.getElementById('login-username');
    const loginPasswordInput = document.getElementById('login-password');
    const regEmailInput = document.getElementById('reg-email');
    const regUsernameInput = document.getElementById('reg-username');
    const regFullnameInput = document.getElementById('reg-fullname');
    const regPasswordInput = document.getElementById('reg-password');

    if (RAG.validator) {
      if (loginUsernameInput) RAG.validator.attachLiveValidation(loginUsernameInput, RAG.validator.validateLoginIdentifier);
      if (loginPasswordInput) RAG.validator.attachLiveValidation(loginPasswordInput, (val) => RAG.validator.validatePassword(val, 6));
      if (regEmailInput) RAG.validator.attachLiveValidation(regEmailInput, RAG.validator.validateEmail);
      if (regUsernameInput) RAG.validator.attachLiveValidation(regUsernameInput, RAG.validator.validateUsername);
      if (regFullnameInput) RAG.validator.attachLiveValidation(regFullnameInput, RAG.validator.validateFullName);
      if (regPasswordInput) RAG.validator.attachLiveValidation(regPasswordInput, (val) => RAG.validator.validatePassword(val, 6));
    }

    loginForm?.addEventListener('submit', (e) => RAG.auth.handleLoginSubmit && RAG.auth.handleLoginSubmit(e));
    registerForm?.addEventListener('submit', (e) => RAG.auth.handleRegisterSubmit && RAG.auth.handleRegisterSubmit(e));

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
        if (RAG.auth.updateAuthUI) RAG.auth.updateAuthUI();
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
        if (RAG.auth.updateAuthUI) RAG.auth.updateAuthUI();
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
      if (RAG.auth.handleLogoutState) RAG.auth.handleLogoutState();
    });

    refreshNowBtn?.addEventListener('click', async () => {
      RAG.utils.showToast('Refreshing tokens...', 'info');
      const success = await API.refreshAuth();
      if (success) {
        RAG.utils.showToast('Tokens successfully refreshed & rotated!', 'success');
        if (RAG.auth.updateAuthUI) RAG.auth.updateAuthUI();
      } else {
        RAG.utils.showToast('Failed to refresh tokens. Please log in again.', 'error');
      }
    });
  }

  RAG.auth.init = initAuthListeners;
})(window);
