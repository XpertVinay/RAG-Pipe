/**
 * Pricing Checkout Handlers, Mandate Creation & Razorpay Verification
 */
(function (global) {
  'use strict';

  global.PricingModule = global.PricingModule || {};
  const P = global.PricingModule;

  P.selectPaymentType = function (type) {
    P.paymentType = type;
    const cardMandate = document.getElementById('type-card-mandate');
    const cardOnetime = document.getElementById('type-card-onetime');

    if (cardMandate && cardOnetime) {
      if (type === 'mandate') {
        cardMandate.classList.add('active');
        cardOnetime.classList.remove('active');
      } else {
        cardOnetime.classList.add('active');
        cardMandate.classList.remove('active');
      }
    }
    if (P.selectedPlanId && P.PLAN_DATA[P.selectedPlanId]) {
      P.updateCheckoutSummary(P.PLAN_DATA[P.selectedPlanId]);
    }
  };

  P.selectPlan = function (planId) {
    P.selectedPlanId = planId;
    const plan = P.PLAN_DATA[planId];
    if (!plan) return;

    if (planId === 'starter') {
      if (window.showToast) {
        window.showToast('Starter tier is active for all accounts by default.', 'info');
      } else {
        alert('Starter tier is active for all accounts by default.');
      }
      return;
    }

    const user = P.getCurrentUser();
    const token = P.getAccessToken();

    if (!user && !token) {
      if (window.showAuthModal) {
        window.showAuthModal('signin', 'Please sign in or register first to upgrade your workspace.');
      } else {
        if (window.showToast) {
          window.showToast('Please sign in or register first to upgrade your workspace.', 'warning');
        }
        setTimeout(() => {
          window.location.href = '/?auth=true';
        }, 1200);
      }
      return;
    }

    P.openCheckoutModal(plan);
  };

  P.openCheckoutModal = function (plan) {
    const modal = document.getElementById('checkout-modal');
    const successView = document.getElementById('checkout-success-view');
    const formView = document.getElementById('checkout-form');

    if (!modal) return;

    P.updateCheckoutSummary(plan);
    P.selectPaymentType('mandate');

    const user = P.getCurrentUser();
    const nameInput = document.getElementById('pay-name');
    const emailInput = document.getElementById('pay-email');
    if (user) {
      if (nameInput && !nameInput.value) nameInput.value = user.full_name || user.username || '';
      if (emailInput && !emailInput.value) emailInput.value = user.email || '';
    }

    if (successView) successView.style.display = 'none';
    if (formView) formView.style.display = 'block';

    modal.style.display = 'flex';
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';

    setTimeout(() => {
      if (nameInput && !nameInput.value) {
        nameInput.focus();
      } else if (emailInput && !emailInput.value) {
        emailInput.focus();
      }
    }, 60);
  };

  P.closeCheckoutModal = function () {
    const modal = document.getElementById('checkout-modal');
    if (!modal) return;
    modal.style.display = 'none';
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  };

  P.setupCheckoutModal = function () {
    const modal = document.getElementById('checkout-modal');
    const closeBtn = document.getElementById('close-checkout-modal-btn');
    const form = document.getElementById('checkout-form');
    const receiptInvoicesBtn = document.getElementById('receipt-view-invoices-btn');

    if (closeBtn) closeBtn.addEventListener('click', P.closeCheckoutModal);
    if (receiptInvoicesBtn) {
      receiptInvoicesBtn.addEventListener('click', () => {
        P.closeCheckoutModal();
        if (P.openInvoicesModal) P.openInvoicesModal();
      });
    }

    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) P.closeCheckoutModal();
      });
    }

    if (form) form.addEventListener('submit', P.handleCheckoutSubmit);
  };

  P.handleCheckoutSubmit = async function (e) {
    if (e && e.preventDefault) e.preventDefault();

    const nameInput = document.getElementById('pay-name');
    const emailInput = document.getElementById('pay-email');
    const submitBtn = document.getElementById('submit-payment-btn');
    const spinner = document.getElementById('pay-btn-spinner');
    const icon = document.getElementById('pay-btn-icon');
    const label = document.getElementById('pay-btn-label');

    P.clearFieldError(nameInput);
    P.clearFieldError(emailInput);

    let isValid = true;
    const billingName = nameInput.value.trim();
    const billingEmail = emailInput.value.trim().toLowerCase();

    if (!billingName || billingName.length < 2) {
      P.showFieldError(nameInput, 'Subscriber / company name is required (min 2 characters).');
      isValid = false;
    }

    const emailRegex = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;
    if (!billingEmail || !emailRegex.test(billingEmail)) {
      P.showFieldError(emailInput, 'Please provide a valid email address for your payment receipt.');
      isValid = false;
    }

    if (!isValid) return;

    const token = P.getAccessToken();
    const user = P.getCurrentUser();
    if (!token && !user) {
      if (window.showAuthModal) {
        window.showAuthModal('signin', 'Please sign in to proceed with checkout.');
      } else if (window.showToast) {
        window.showToast('Please sign in to proceed with checkout.', 'warning');
      }
      return;
    }

    try {
      if (submitBtn) submitBtn.disabled = true;
      if (spinner) spinner.style.display = 'inline-block';
      if (icon) icon.style.display = 'none';
      if (label) label.textContent = 'Connecting to Razorpay...';

      if (P.paymentType === 'mandate') {
        const mandateData = await P.apiPost('/api/pricing/razorpay/create-mandate', {
          plan_id: P.selectedPlanId,
          billing_cycle: 'monthly',
          billing_name: billingName,
          billing_email: billingEmail,
          total_count: 12,
          immediate_charge: true,
        });

        const isRealKey = mandateData.key_id && !mandateData.key_id.includes('placeholder') && !mandateData.key_id.startsWith('rzp_test_placeholder');
        if (typeof window.Razorpay === 'function' && isRealKey) {
          const rzpOptions = {
            key: mandateData.key_id,
            subscription_id: mandateData.subscription_id,
            name: 'RAG Agent Intelligence',
            description: `Mandate: ${mandateData.plan_name} (${mandateData.billing_cycle})`,
            prefill: { name: billingName, email: billingEmail },
            theme: { color: '#6366f1' },
            handler: async function (response) {
              await P.verifyRazorpayMandate(response);
            },
            modal: {
              ondismiss: function () {
                P.resetSubmitBtn();
                if (window.showToast) window.showToast('Mandate setup dismissed.', 'info');
              },
            },
          };
          const rzp = new window.Razorpay(rzpOptions);
          rzp.on('payment.failed', function (resp) {
            if (window.showToast) window.showToast(`Mandate setup failed: ${resp.error?.description || 'Gateway error'}`, 'error');
            P.resetSubmitBtn();
          });
          rzp.open();
        } else {
          setTimeout(async () => {
            const mockMandateResponse = {
              razorpay_subscription_id: mandateData.subscription_id,
              razorpay_payment_id: `pay_mnd_${Date.now()}`,
              razorpay_signature: `sig_sandbox_${Date.now()}`,
            };
            await P.verifyRazorpayMandate(mockMandateResponse);
          }, 600);
        }
      } else {
        const orderData = await P.apiPost('/api/pricing/razorpay/create-order', {
          plan_id: P.selectedPlanId,
          billing_cycle: P.currentCycle,
          billing_name: billingName,
          billing_email: billingEmail,
        });

        const isRealKey = orderData.key_id && !orderData.key_id.includes('placeholder') && !orderData.key_id.startsWith('rzp_test_placeholder');
        if (typeof window.Razorpay === 'function' && isRealKey) {
          const rzpOptions = {
            key: orderData.key_id,
            amount: orderData.amount_paise,
            currency: orderData.currency,
            name: 'RAG Agent Intelligence',
            description: `${orderData.plan_name} (${orderData.billing_cycle})`,
            order_id: orderData.order_id,
            prefill: { name: billingName, email: billingEmail },
            theme: { color: '#6366f1' },
            handler: async function (response) {
              await P.verifyRazorpayPayment(response, token);
            },
            modal: {
              ondismiss: function () {
                P.resetSubmitBtn();
                if (window.showToast) window.showToast('Razorpay checkout closed.', 'info');
              },
            },
          };
          const rzp = new window.Razorpay(rzpOptions);
          rzp.on('payment.failed', function (resp) {
            if (window.showToast) window.showToast(`Payment failed: ${resp.error?.description || 'Gateway error'}`, 'error');
            P.resetSubmitBtn();
          });
          rzp.open();
        } else {
          setTimeout(async () => {
            const mockPaymentResponse = {
              razorpay_order_id: orderData.order_id,
              razorpay_payment_id: `pay_mock_${Date.now()}`,
              razorpay_signature: `sig_sandbox_${Date.now()}`,
            };
            await P.verifyRazorpayPayment(mockPaymentResponse, token);
          }, 600);
        }
      }
    } catch (err) {
      if (window.showToast) window.showToast(err.message, 'error');
      else alert(err.message);
      P.resetSubmitBtn();
    }
  };

  P.verifyRazorpayMandate = async function (rzpResponse) {
    const label = document.getElementById('pay-btn-label');
    try {
      if (label) label.textContent = 'Verifying Mandate Signature...';
      const verifyData = await P.apiPost('/api/pricing/razorpay/verify-mandate', {
        razorpay_subscription_id: rzpResponse.razorpay_subscription_id,
        razorpay_payment_id: rzpResponse.razorpay_payment_id,
        razorpay_signature: rzpResponse.razorpay_signature,
      });

      const formView = document.getElementById('checkout-form');
      const successView = document.getElementById('checkout-success-view');
      const titleEl = document.getElementById('receipt-title');
      const successMsg = document.getElementById('checkout-success-msg');
      const payIdEl = document.getElementById('receipt-pay-id');
      const orderIdEl = document.getElementById('receipt-order-id');
      const statusLabelEl = document.getElementById('receipt-status-label');

      if (formView) formView.style.display = 'none';
      if (successView) successView.style.display = 'block';
      if (titleEl) titleEl.textContent = 'Auto-Debit Mandate Confirmed!';
      if (successMsg) successMsg.textContent = verifyData.message;
      if (payIdEl) payIdEl.textContent = verifyData.transaction_id;
      if (orderIdEl) orderIdEl.textContent = rzpResponse.razorpay_subscription_id;
      if (statusLabelEl) statusLabelEl.textContent = 'Active Mandate • Verified';

      P.updateUserSessionAdmin();
      if (window.showToast) window.showToast('Razorpay Mandate active! Initial invoice generated.', 'success');
    } catch (err) {
      if (window.showToast) window.showToast(err.message, 'error');
      else alert(err.message);
      P.resetSubmitBtn();
    }
  };

  P.verifyRazorpayPayment = async function (rzpResponse) {
    const label = document.getElementById('pay-btn-label');
    try {
      if (label) label.textContent = 'Verifying Gateway Signature...';
      const verifyData = await P.apiPost('/api/pricing/razorpay/verify-payment', {
        razorpay_order_id: rzpResponse.razorpay_order_id,
        razorpay_payment_id: rzpResponse.razorpay_payment_id,
        razorpay_signature: rzpResponse.razorpay_signature,
      });

      const formView = document.getElementById('checkout-form');
      const successView = document.getElementById('checkout-success-view');
      const titleEl = document.getElementById('receipt-title');
      const successMsg = document.getElementById('checkout-success-msg');
      const payIdEl = document.getElementById('receipt-pay-id');
      const orderIdEl = document.getElementById('receipt-order-id');
      const statusLabelEl = document.getElementById('receipt-status-label');

      if (formView) formView.style.display = 'none';
      if (successView) successView.style.display = 'block';
      if (titleEl) titleEl.textContent = 'Payment Confirmed!';
      if (successMsg) successMsg.textContent = verifyData.message;
      if (payIdEl) payIdEl.textContent = verifyData.transaction_id;
      if (orderIdEl) orderIdEl.textContent = rzpResponse.razorpay_order_id;
      if (statusLabelEl) statusLabelEl.textContent = 'Paid • Verified';

      P.updateUserSessionAdmin();
      if (window.showToast) window.showToast('Subscription payment confirmed!', 'success');
    } catch (err) {
      if (window.showToast) window.showToast(err.message, 'error');
      else alert(err.message);
      P.resetSubmitBtn();
    }
  };

  P.updateUserSessionAdmin = function (token) {
    const user = P.getCurrentUser();
    if (user) {
      user.role = 'admin';
      if (typeof API !== 'undefined' && API.saveAuthSession) {
        API.saveAuthSession({ access_token: token, user: user });
      }
    }
  };
})(window);
