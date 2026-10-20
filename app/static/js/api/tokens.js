/**
 * API Tokens & Session Storage Management
 */
(function (global) {
  'use strict';

  global.API = global.API || {};
  const API = global.API;

  API.API_VERSION = 'v1';
  API.BASE_URL = '/api/v1';
  API.TOKEN_KEY = 'rag_access_token';
  API.ID_TOKEN_KEY = 'rag_id_token';
  API.REFRESH_TOKEN_KEY = 'rag_refresh_token';
  API.USER_KEY = 'rag_user';
  API.ACTIVE_ROOM_KEY = 'rag_active_room_id';

  API.getAccessToken = function () {
    return localStorage.getItem(API.TOKEN_KEY);
  };

  API.getIdToken = function () {
    return localStorage.getItem(API.ID_TOKEN_KEY);
  };

  API.getRefreshToken = function () {
    return localStorage.getItem(API.REFRESH_TOKEN_KEY);
  };

  API.getCurrentUser = function () {
    try {
      const u = localStorage.getItem(API.USER_KEY);
      return u ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  };

  API.getActiveRoomId = function () {
    return localStorage.getItem(API.ACTIVE_ROOM_KEY);
  };

  API.setActiveRoomId = function (roomId) {
    if (roomId) {
      localStorage.setItem(API.ACTIVE_ROOM_KEY, roomId);
    } else {
      localStorage.removeItem(API.ACTIVE_ROOM_KEY);
    }
  };

  API.syncCookieToken = function () {
    const token = API.getAccessToken();
    if (token) {
      document.cookie = `access_token=${encodeURIComponent(token)}; path=/; max-age=604800; SameSite=Lax`;
    }
  };

  API.setAuthSession = function (tokenData) {
    if (tokenData.access_token) {
      localStorage.setItem(API.TOKEN_KEY, tokenData.access_token);
      document.cookie = `access_token=${encodeURIComponent(tokenData.access_token)}; path=/; max-age=604800; SameSite=Lax`;
    }
    if (tokenData.id_token) {
      localStorage.setItem(API.ID_TOKEN_KEY, tokenData.id_token);
    }
    if (tokenData.refresh_token) {
      localStorage.setItem(API.REFRESH_TOKEN_KEY, tokenData.refresh_token);
    }
    if (tokenData.user) {
      localStorage.setItem(API.USER_KEY, JSON.stringify(tokenData.user));
      window.currentUser = tokenData.user;
      window.dispatchEvent(new CustomEvent('auth:login', { detail: { user: tokenData.user } }));
    }
  };

  API.clearAuthSession = function () {
    localStorage.removeItem(API.TOKEN_KEY);
    localStorage.removeItem(API.ID_TOKEN_KEY);
    localStorage.removeItem(API.REFRESH_TOKEN_KEY);
    localStorage.removeItem(API.USER_KEY);
    localStorage.removeItem(API.ACTIVE_ROOM_KEY);
    localStorage.removeItem('rag_active_conv_id');
    document.cookie = 'access_token=; path=/; max-age=0; SameSite=Lax';
    document.cookie = 'token=; path=/; max-age=0; SameSite=Lax';
    window.currentUser = null;
    window.dispatchEvent(new CustomEvent('auth:logout'));
  };
})(window);
