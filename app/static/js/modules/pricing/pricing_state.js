/**
 * Pricing Plan Configurations, State & Session Tokens
 */
(function (global) {
  'use strict';

  global.PricingModule = global.PricingModule || {};
  const P = global.PricingModule;

  P.currentCycle = 'monthly';
  P.selectedPlanId = 'pro';
  P.paymentType = 'mandate'; // 'mandate' (auto-debit recurring) or 'onetime'
  P.cachedInvoices = [];
  P.cachedMandateStatus = null;

  P.rzpPublicConfig = {
    key_id: 'rzp_test_placeholder_key',
    currency: 'INR',
    is_test_mode: true,
  };

  P.PLAN_DATA = {
    starter: {
      id: 'starter',
      name: 'Starter Plan',
      inr_monthly: 0,
      inr_annual: 0,
      usd_monthly: 0,
      usd_annual: 0,
      seats: '1 Seat',
    },
    pro: {
      id: 'pro',
      name: 'Professional Plan',
      inr_monthly: 3999,
      inr_annual: 3199,
      usd_monthly: 49,
      usd_annual: 39,
      seats: 'Up to 15 Seats',
    },
    enterprise: {
      id: 'enterprise',
      name: 'Enterprise Plan',
      inr_monthly: 19999,
      inr_annual: 15999,
      usd_monthly: 249,
      usd_annual: 199,
      seats: 'Unlimited Seats',
    },
  };

  P.getCurrentUser = function () {
    if (window.currentUser) return window.currentUser;
    if (typeof API !== 'undefined' && API.getCurrentUser) {
      const u = API.getCurrentUser();
      if (u) {
        window.currentUser = u;
        return u;
      }
    }
    try {
      const raw = localStorage.getItem('rag_user') || localStorage.getItem('rag_current_user');
      if (raw) {
        const u = JSON.parse(raw);
        window.currentUser = u;
        return u;
      }
    } catch (_) {}
    return null;
  };

  P.getAccessToken = function () {
    if (typeof API !== 'undefined' && API.getAccessToken) {
      return API.getAccessToken();
    }
    return localStorage.getItem('rag_access_token');
  };
})(window);
