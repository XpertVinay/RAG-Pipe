/**
 * Pricing UI Controls, Cycle Toggles, Modals & Dynamic Form Displays
 */
(function (global) {
  'use strict';

  global.PricingModule = global.PricingModule || {};
  const P = global.PricingModule;

  P.updatePricingDisplay = function () {
    const isINR = P.rzpPublicConfig.currency === 'INR';
    const sym = isINR ? '₹' : '$';

    const pricePro = document.getElementById('price-pro');
    const priceEnterprise = document.getElementById('price-enterprise');
    const currencyPills = document.querySelectorAll('.card-price-currency');

    currencyPills.forEach((el) => {
      el.textContent = sym;
    });

    if (P.currentCycle === 'monthly') {
      if (pricePro) pricePro.textContent = isINR ? '3,999' : '49';
      if (priceEnterprise) priceEnterprise.textContent = isINR ? '19,999' : '249';
    } else {
      if (pricePro) pricePro.textContent = isINR ? '3,199' : '39';
      if (priceEnterprise) priceEnterprise.textContent = isINR ? '15,999' : '199';
    }
  };

  P.updateUserStatus = function () {
    const userLabel = document.getElementById('pricing-user-label');
    const avatar = document.getElementById('pricing-avatar');
    const authBtn = document.getElementById('pricing-auth-btn');

    if (!userLabel || !avatar) return;

    const user = P.getCurrentUser();

    if (user) {
      userLabel.textContent = user.username || user.full_name || 'Account';
      avatar.textContent = (user.username || 'U')[0].toUpperCase();
      if (authBtn) {
        authBtn.onclick = () => {
          window.location.href = '/';
        };
      }
    } else {
      userLabel.textContent = 'Sign In';
      avatar.textContent = '👤';
      if (authBtn) {
        authBtn.onclick = () => {
          window.location.href = '/?auth=true';
        };
      }
    }
  };

  P.setupCycleToggle = function () {
    const btnMonthly = document.getElementById('toggle-monthly');
    const btnAnnual = document.getElementById('toggle-annual');
    const periodPro = document.getElementById('period-pro');
    const periodEnterprise = document.getElementById('period-enterprise');

    if (!btnMonthly || !btnAnnual) return;

    btnMonthly.addEventListener('click', () => {
      P.currentCycle = 'monthly';
      btnMonthly.classList.add('active');
      btnAnnual.classList.remove('active');
      if (periodPro) periodPro.textContent = '/ month';
      if (periodEnterprise) periodEnterprise.textContent = '/ month';
      P.updatePricingDisplay();
      const modal = document.getElementById('checkout-modal');
      if (modal && modal.style.display === 'flex') {
        const plan = P.PLAN_DATA[P.selectedPlanId];
        if (plan) P.updateCheckoutSummary(plan);
      }
    });

    btnAnnual.addEventListener('click', () => {
      P.currentCycle = 'annual';
      btnAnnual.classList.add('active');
      btnMonthly.classList.remove('active');
      if (periodPro) periodPro.textContent = '/ month (billed annually)';
      if (periodEnterprise) periodEnterprise.textContent = '/ month (billed annually)';
      P.updatePricingDisplay();
      const modal = document.getElementById('checkout-modal');
      if (modal && modal.style.display === 'flex') {
        const plan = P.PLAN_DATA[P.selectedPlanId];
        if (plan) P.updateCheckoutSummary(plan);
      }
    });
  };

  P.updateCheckoutSummary = function (plan) {
    if (!plan) return;
    const planNameEl = document.getElementById('summary-plan-name');
    const cycleEl = document.getElementById('summary-billing-cycle');
    const amountEl = document.getElementById('summary-amount-due');
    const currencyLabelEl = document.getElementById('summary-currency-label');
    const label = document.getElementById('pay-btn-label');

    const isINR = P.rzpPublicConfig.currency === 'INR';
    const sym = isINR ? '₹' : '$';

    if (P.paymentType === 'mandate') {
      const price = isINR ? plan.inr_monthly : plan.usd_monthly;
      if (planNameEl) planNameEl.textContent = plan.name;
      if (cycleEl) cycleEl.textContent = `Monthly Recurring Mandate • Auto-Debit (every 30 days) • ${plan.seats}`;
      if (amountEl) amountEl.textContent = `${sym}${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      if (currencyLabelEl) currencyLabelEl.textContent = `${P.rzpPublicConfig.currency} / month (Recurring)`;
      if (label && !label.textContent.includes('Connecting') && !label.textContent.includes('Verifying')) {
        label.textContent = `Set Up Monthly Mandate (${sym}${price.toLocaleString('en-US')} / mo)`;
      }
      return;
    }

    let price = 0;
    if (isINR) {
      price = P.currentCycle === 'annual' ? plan.inr_annual * 12 : plan.inr_monthly;
    } else {
      price = P.currentCycle === 'annual' ? plan.usd_annual * 12 : plan.usd_monthly;
    }

    const cycleLabel = P.currentCycle === 'annual' ? 'Annual Billing (Billed Annually)' : 'Monthly Billing';
    if (planNameEl) planNameEl.textContent = plan.name;
    if (cycleEl) cycleEl.textContent = `${cycleLabel} • ${plan.seats}`;
    if (amountEl) amountEl.textContent = `${sym}${price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    if (currencyLabelEl) currencyLabelEl.textContent = `${P.rzpPublicConfig.currency} / period`;
    if (label && !label.textContent.includes('Connecting') && !label.textContent.includes('Verifying')) {
      label.textContent = `Pay ${sym}${price.toLocaleString('en-US')} with Razorpay Gateway`;
    }
  };

  P.showFieldError = function (inputEl, msg) {
    if (!inputEl) return;
    P.clearFieldError(inputEl);
    inputEl.classList.add('is-invalid');

    if (window.RAGValidator && typeof window.RAGValidator.showError === 'function') {
      window.RAGValidator.showError(inputEl, msg);
    } else {
      const err = document.createElement('div');
      err.className = 'field-error-msg';
      err.setAttribute('data-for', inputEl.id || '');
      err.innerHTML = `<span style="font-size: 0.8rem;">⚠️</span> <span>${msg}</span>`;
      if (inputEl.nextSibling) {
        inputEl.parentNode.insertBefore(err, inputEl.nextSibling);
      } else {
        inputEl.parentNode.appendChild(err);
      }
    }
  };

  P.clearFieldError = function (inputEl) {
    if (!inputEl) return;
    inputEl.classList.remove('is-invalid');
    if (window.RAGValidator && typeof window.RAGValidator.clearError === 'function') {
      window.RAGValidator.clearError(inputEl);
    } else {
      const existing = inputEl.parentNode ? inputEl.parentNode.querySelector(`.field-error-msg[data-for="${inputEl.id || ''}"]`) : null;
      if (existing) existing.remove();
    }
  };

  P.resetSubmitBtn = function () {
    const submitBtn = document.getElementById('submit-payment-btn');
    const spinner = document.getElementById('pay-btn-spinner');
    const icon = document.getElementById('pay-btn-icon');
    const label = document.getElementById('pay-btn-label');

    if (submitBtn) submitBtn.disabled = false;
    if (spinner) spinner.style.display = 'none';
    if (icon) icon.style.display = 'inline';
    if (P.selectedPlanId && P.PLAN_DATA[P.selectedPlanId]) {
      P.updateCheckoutSummary(P.PLAN_DATA[P.selectedPlanId]);
    } else if (label) {
      label.textContent = P.paymentType === 'mandate' ? 'Set Up Monthly Mandate (Razorpay)' : 'Pay with Razorpay Gateway';
    }
  };
})(window);
