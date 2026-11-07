/**
 * Authentication & JWT Token Management Module
 * Modular Facade unifying UI indicators, tab switching, and auth actions.
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.auth = RAG.auth || {};

  // Bind top-level global handlers for inline DOM event triggers
  global.updateAuthUI = () => RAG.auth.updateAuthUI && RAG.auth.updateAuthUI();
  global.switchAuthTab = (tab) => RAG.auth.switchAuthTab && RAG.auth.switchAuthTab(tab);
  global.showAuthModal = (tab, msg) => RAG.auth.showAuthModal && RAG.auth.showAuthModal(tab, msg);
  global.handleLogoutState = () => RAG.auth.handleLogoutState && RAG.auth.handleLogoutState();
  global.copyToken = (type) => RAG.auth.copyToken && RAG.auth.copyToken(type);
})(window);
