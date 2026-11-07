/**
 * Production RAG Agent Client API Service
 * Modular Facade unifying tokens, client interceptor, and domain endpoints.
 */
(function (global) {
  'use strict';

  global.API = global.API || {};
  const API = global.API;

  try {
    if (API.syncCookieToken) {
      API.syncCookieToken();
    }
  } catch (e) {
    console.warn('Could not sync cookie token:', e);
  }
})(window);
