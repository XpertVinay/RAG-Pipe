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
  API.DEVICE_ID_KEY = 'rag_device_id';
  API.DEVICE_FINGERPRINT_KEY = 'rag_device_fingerprint';

  // ---------------------------------------------------------------------------
  // Digital Device Fingerprint & Verified Device Token Architecture
  // ---------------------------------------------------------------------------
  // Solves the Corporate NAT/VPN Shared-IP problem by uniquely tagging verified
  // client devices so each employee gets their own dedicated rate limit quota.
  API.getOrCreateDeviceId = function () {
    let deviceId = localStorage.getItem(API.DEVICE_ID_KEY);
    if (!deviceId) {
      if (window.crypto && window.crypto.randomUUID) {
        deviceId = window.crypto.randomUUID();
      } else {
        deviceId = 'dev_' + Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
      }
      localStorage.setItem(API.DEVICE_ID_KEY, deviceId);
    }
    // Also synchronize to cookie so non-JS socket probes / raw page transitions carry device identity
    try {
      document.cookie = `rag_device_id=${encodeURIComponent(deviceId)}; path=/; max-age=31536000; SameSite=Lax`;
    } catch (_) {}
    return deviceId;
  };

  API.getDeviceFingerprint = function () {
    let fp = localStorage.getItem(API.DEVICE_FINGERPRINT_KEY);
    if (!fp) {
      try {
        const screenStr = `${window.screen?.width || 0}x${window.screen?.height || 0}x${window.screen?.colorDepth || 0}`;
        const tz = Intl?.DateTimeFormat?.().resolvedOptions?.()?.timeZone || 'UTC';
        const nav = `${navigator.language || ''}|${navigator.hardwareConcurrency || 1}|${navigator.platform || ''}`;

        // Lightweight hardware canvas entropy hash
        let canvasHash = 'c0';
        try {
          const canvas = document.createElement('canvas');
          const ctx = canvas.getContext('2d');
          if (ctx) {
            ctx.textBaseline = 'top';
            ctx.font = "14px 'Arial'";
            ctx.textBaseline = 'alphabetic';
            ctx.fillStyle = '#f60';
            ctx.fillRect(125, 1, 62, 20);
            ctx.fillStyle = '#069';
            ctx.fillText('RAG-Device-FP', 2, 15);
            canvasHash = canvas.toDataURL().slice(-32);
          }
        } catch (_) {}

        // Fast string hash (djb2)
        const raw = `${screenStr}|${tz}|${nav}|${canvasHash}`;
        let hash = 5381;
        for (let i = 0; i < raw.length; i++) {
          hash = ((hash << 5) + hash) + raw.charCodeAt(i);
          hash = hash & hash;
        }
        fp = 'fp_' + Math.abs(hash).toString(36);
        localStorage.setItem(API.DEVICE_FINGERPRINT_KEY, fp);
      } catch (_) {
        fp = 'fp_default';
      }
    }
    return fp;
  };

  // Pre-seed device credentials on initial script execution
  try {
    API.getOrCreateDeviceId();
    API.getDeviceFingerprint();
  } catch (_) {}

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
