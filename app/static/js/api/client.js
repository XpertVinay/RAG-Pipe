/**
 * Core HTTP Request Wrapper, Interceptor & Automatic Token Refresher
 */
(function (global) {
  'use strict';

  global.API = global.API || {};
  const API = global.API;

  API.request = async function (url, options = {}, isRetry = false) {
    const headers = { ...(options.headers || {}) };
    const token = API.getAccessToken();

    if (token && (!headers['Authorization'] || isRetry)) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    if (!headers['X-API-Version']) {
      headers['X-API-Version'] = API.API_VERSION;
    }

    const res = await fetch(url, { ...options, headers });

    // Handle 401 Unauthorized with token refresh retry
    if (res.status === 401 && !isRetry && !url.includes('/auth/')) {
      const refreshed = await API.refreshAuth();
      if (refreshed) {
        return API.request(url, options, true);
      }
      API.clearAuthSession();
      if (window.showAuthModal) {
        window.showAuthModal('signin', 'Authentication required. Please sign in or register.');
      }
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      let detailMsg = err.detail || err.message;
      if (Array.isArray(detailMsg)) {
        detailMsg = detailMsg
          .map((d) => (d.loc ? `${d.loc.filter((x) => x !== 'body').join('.')}: ${d.msg}` : d.msg || JSON.stringify(d)))
          .join('; ');
      } else if (typeof detailMsg === 'object' && detailMsg !== null) {
        detailMsg = detailMsg.msg || detailMsg.message || JSON.stringify(detailMsg);
      }
      throw new Error(detailMsg || 'API request failed');
    }

    return res.json();
  };

  API.get = async function (url) {
    return API.request(url, { method: 'GET' });
  };

  API.post = async function (url, data) {
    return API.request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  };

  API.put = async function (url, data) {
    return API.request(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  };

  API.patch = async function (url, data) {
    return API.request(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  };

  API.delete = async function (url) {
    return API.request(url, { method: 'DELETE' });
  };
})(window);
