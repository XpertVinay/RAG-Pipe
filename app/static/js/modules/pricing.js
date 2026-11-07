/**
 * Razorpay Payment Gateway, Auto-Debit Mandate & Invoicing Transparency Module
 * Modular Facade orchestrating pricing state, checkout, and invoice components.
 */
(function (global) {
  'use strict';

  global.PricingModule = global.PricingModule || {};
  const P = global.PricingModule;

  function initPricing() {
    if (P.setupCycleToggle) P.setupCycleToggle();
    if (P.setupCheckoutModal) P.setupCheckoutModal();
    if (P.setupInvoicesModal) P.setupInvoicesModal();
    if (P.updateUserStatus) P.updateUserStatus();
    if (P.fetchRazorpayConfig) P.fetchRazorpayConfig();

    window.addEventListener('auth:login', () => {
      if (P.updateUserStatus) P.updateUserStatus();
    });
    window.addEventListener('auth:logout', () => {
      if (P.updateUserStatus) P.updateUserStatus();
    });
  }

  // Global Window Interface Bindings for Inline DOM and Template Events
  global.selectPaymentType = (type) => P.selectPaymentType && P.selectPaymentType(type);
  global.selectPlan = (planId) => P.selectPlan && P.selectPlan(planId);
  global.openCheckoutModal = (plan) => P.openCheckoutModal && P.openCheckoutModal(plan);
  global.closeCheckoutModal = () => P.closeCheckoutModal && P.closeCheckoutModal();
  global.handleCheckoutClick = (e) => P.handleCheckoutSubmit && P.handleCheckoutSubmit(e);
  global.openInvoicesModal = () => P.openInvoicesModal && P.openInvoicesModal();
  global.closeInvoicesModal = () => P.closeInvoicesModal && P.closeInvoicesModal();
  global.syncMandateTransactions = () => P.syncMandateTransactions && P.syncMandateTransactions();
  global.viewInvoiceDetail = (id) => P.viewInvoiceDetail && P.viewInvoiceDetail(id);
  global.closeInvoiceDetail = () => P.closeInvoiceDetail && P.closeInvoiceDetail();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPricing);
  } else {
    initPricing();
  }
})(window);
