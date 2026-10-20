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

    authUserBtn?.addEventListener('click', () => {
      const user = API.getCurrentUser();
      if (RAG.auth.switchAuthTab) RAG.auth.switchAuthTab(user ? 'tokens' : 'signin');
      authModal?.classList.add('active');
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
