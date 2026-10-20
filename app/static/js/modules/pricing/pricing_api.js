/**
 * Pricing API Communications & Gateway Endpoint Fetchers
 */
(function (global) {
  'use strict';

  global.PricingModule = global.PricingModule || {};
  const P = global.PricingModule;

  P.apiFetch = async function (endpoint, options = {}) {
    if (typeof API !== 'undefined' && API.request) {
      return API.request(endpoint, options);
    }
    const token = P.getAccessToken();
    const headers = { ...(options.headers || {}) };
    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    const res = await fetch(endpoint, { ...options, headers });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || err.message || 'API request failed');
    }
    return res.json();
  };

  P.apiGet = async function (endpoint) {
    return P.apiFetch(endpoint, { method: 'GET' });
  };

  P.apiPost = async function (endpoint, data = {}) {
    return P.apiFetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  };

  P.fetchRazorpayConfig = async function () {
    try {
      const data = await P.apiGet('/api/pricing/razorpay/config');
      P.rzpPublicConfig = data;
      if (P.updatePricingDisplay) {
        P.updatePricingDisplay();
      }
    } catch (err) {
      console.warn('Could not fetch Razorpay config, using default settings:', err);
    }
  };
})(window);
