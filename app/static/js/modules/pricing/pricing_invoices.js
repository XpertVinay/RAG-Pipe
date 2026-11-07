/**
 * Pricing Invoices Modal, Transparency History & Auto-Debit Status
 */
(function (global) {
  'use strict';

  global.PricingModule = global.PricingModule || {};
  const P = global.PricingModule;

  P.setupInvoicesModal = function () {
    const viewBtn = document.getElementById('view-invoices-btn');
    const modal = document.getElementById('invoices-modal');
    const closeBtn = document.getElementById('close-invoices-modal-btn');
    const syncBtn = document.getElementById('sync-mandate-btn');
    const closeDetailBtn = document.getElementById('close-invoice-detail-btn');

    if (viewBtn) viewBtn.addEventListener('click', P.openInvoicesModal);
    if (closeBtn) closeBtn.addEventListener('click', P.closeInvoicesModal);
    if (syncBtn) syncBtn.addEventListener('click', P.syncMandateTransactions);
    if (closeDetailBtn) closeDetailBtn.addEventListener('click', P.closeInvoiceDetail);

    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) P.closeInvoicesModal();
      });
    }

    const detailModal = document.getElementById('invoice-detail-modal');
    if (detailModal) {
      detailModal.addEventListener('click', (e) => {
        if (e.target === detailModal) P.closeInvoiceDetail();
      });
    }
  };

  P.openInvoicesModal = async function () {
    const token = P.getAccessToken();
    const user = P.getCurrentUser();
    if (!token && !user) {
      if (window.showAuthModal) {
        window.showAuthModal('signin', 'Please sign in to view your organization invoices & mandates.');
      } else {
        if (window.showToast) window.showToast('Please sign in to view your organization invoices & mandates.', 'warning');
        setTimeout(() => { window.location.href = '/?auth=true'; }, 1000);
      }
      return;
    }

    const modal = document.getElementById('invoices-modal');
    if (!modal) return;

    modal.style.display = 'flex';
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden';

    await P.loadMandateStatus();
    await P.loadInvoicesList();
  };

  P.closeInvoicesModal = function () {
    const modal = document.getElementById('invoices-modal');
    if (!modal) return;
    modal.style.display = 'none';
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = '';
  };

  P.loadMandateStatus = async function () {
    try {
      const data = await P.apiGet('/api/pricing/mandate/status');
      P.cachedMandateStatus = data;
      P.renderMandateStatus(data);
    } catch (err) {
      console.warn('Could not load mandate status:', err);
    }
  };

  P.renderMandateStatus = function (data) {
    const planEl = document.getElementById('inv-stat-plan');
    const statusEl = document.getElementById('inv-stat-mandate-status');
    const mandateIdEl = document.getElementById('inv-stat-mandate-id');
    const nextChargeEl = document.getElementById('inv-stat-next-charge');
    const countEl = document.getElementById('invoices-count');

    if (planEl) planEl.textContent = (data.plan_tier || 'starter').toUpperCase();

    if (statusEl) {
      const status = (data.mandate_status || 'none').toLowerCase();
      statusEl.textContent = status.toUpperCase();
      statusEl.className = 'status-badge';
      if (status === 'active') statusEl.classList.add('status-badge-active');
      else if (status === 'pending' || status === 'created') statusEl.classList.add('status-badge-pending');
      else statusEl.classList.add('status-badge-none');
    }

    if (mandateIdEl) {
      mandateIdEl.textContent = data.mandate_id || '—';
      mandateIdEl.title = data.mandate_id || 'No active mandate';
    }

    if (nextChargeEl) {
      if (data.mandate_next_charge_at) {
        const dt = new Date(data.mandate_next_charge_at);
        nextChargeEl.textContent = dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      } else {
        nextChargeEl.textContent = '—';
      }
    }

    if (countEl) countEl.textContent = data.invoices_count || 0;
  };

  P.loadInvoicesList = async function () {
    const tbody = document.getElementById('invoices-table-body');
    if (!tbody) return;

    try {
      const invoices = await P.apiGet('/api/pricing/invoices');
      P.cachedInvoices = invoices;
      P.renderInvoicesTable(invoices);
    } catch (err) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; padding: 28px; color: #ef4444;">
            ⚠️ Could not load invoices: ${err.message}
          </td>
        </tr>
      `;
    }
  };

  P.renderInvoicesTable = function (invoices) {
    const tbody = document.getElementById('invoices-table-body');
    const countEl = document.getElementById('invoices-count');
    if (!tbody) return;

    if (countEl) countEl.textContent = invoices.length;

    if (!invoices || invoices.length === 0) {
      tbody.innerHTML = `
        <tr>
          <td colspan="7" style="text-align: center; padding: 36px 20px; color: #94a3b8;">
            <div style="font-size: 2rem; margin-bottom: 8px;">📑</div>
            <div style="font-weight: 600; color: #cbd5e1; margin-bottom: 4px;">No Invoices Generated Yet</div>
            <div style="font-size: 0.78rem; color: #64748b; max-width: 400px; margin: 0 auto;">
              When you purchase a subscription plan or activate an auto-debit mandate, all transactions are recorded transparently here.
            </div>
          </td>
        </tr>
      `;
      return;
    }

    let html = '';
    invoices.forEach((inv) => {
      const dt = inv.paid_at || inv.created_at ? new Date(inv.paid_at || inv.created_at) : new Date();
      const dateStr = dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
      const sym = inv.currency === 'INR' ? '₹' : '$';
      const amountFormatted = `${sym}${inv.amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

      const statusBadge = inv.status === 'paid'
        ? `<span class="status-badge status-badge-paid">PAID</span>`
        : `<span class="status-badge status-badge-pending">${inv.status.toUpperCase()}</span>`;

      const refText = inv.razorpay_payment_id || inv.razorpay_subscription_id || inv.razorpay_invoice_id || '—';
      const shortRef = refText.length > 20 ? refText.substring(0, 18) + '...' : refText;

      html += `
        <tr>
          <td style="font-family: monospace; font-weight: 700; color: #a5b4fc;">${inv.invoice_number}</td>
          <td style="color: #cbd5e1; font-size: 0.8rem;">${dateStr}</td>
          <td>
            <div style="font-weight: 600; color: #ffffff;">${(inv.plan_id || 'Plan').toUpperCase()}</div>
            <div style="font-size: 0.72rem; color: #94a3b8;">${inv.billing_cycle || 'monthly'}</div>
          </td>
          <td style="font-weight: 700; color: #34d399;">${amountFormatted}</td>
          <td style="font-family: monospace; font-size: 0.75rem; color: #94a3b8;" title="${refText}">${shortRef}</td>
          <td>${statusBadge}</td>
          <td style="text-align: right;">
            <button type="button" class="receipt-btn" onclick="window.viewInvoiceDetail('${inv.id}')">
              <span>🧾</span> <span>Receipt</span>
            </button>
          </td>
        </tr>
      `;
    });

    tbody.innerHTML = html;
  };

  P.syncMandateTransactions = async function () {
    const token = P.getAccessToken();
    const user = P.getCurrentUser();
    if (!token && !user) {
      if (window.showAuthModal) window.showAuthModal('signin', 'Please sign in to sync your mandate transactions.');
      else if (window.showToast) window.showToast('Please sign in to sync your mandate transactions.', 'warning');
      return;
    }

    const syncBtn = document.getElementById('sync-mandate-btn');
    const syncIcon = document.getElementById('sync-icon');
    const syncLabel = document.getElementById('sync-label');
    const lastSyncTimeEl = document.getElementById('last-sync-time');

    try {
      if (syncBtn) syncBtn.disabled = true;
      if (syncIcon) syncIcon.classList.add('sync-spin');
      if (syncLabel) syncLabel.textContent = 'Syncing...';

      const data = await P.apiPost('/api/pricing/mandate/sync', {});
      if (window.showToast) window.showToast(data.message, data.new_invoices_created > 0 ? 'success' : 'info');
      if (lastSyncTimeEl) lastSyncTimeEl.textContent = `Synced just now (${new Date().toLocaleTimeString()})`;

      await P.loadMandateStatus();
      await P.loadInvoicesList();
    } catch (err) {
      if (window.showToast) window.showToast(err.message, 'error');
      else alert(err.message);
    } finally {
      if (syncBtn) syncBtn.disabled = false;
      if (syncIcon) syncIcon.classList.remove('sync-spin');
      if (syncLabel) syncLabel.textContent = 'Sync from Razorpay';
    }
  };

  P.viewInvoiceDetail = function (invoiceId) {
    const inv = P.cachedInvoices.find((i) => i.id === invoiceId);
    if (!inv) return;

    const modal = document.getElementById('invoice-detail-modal');
    const titleNum = document.getElementById('invoice-detail-num');
    const content = document.getElementById('invoice-detail-content');

    if (!modal || !content) return;
    if (titleNum) titleNum.textContent = inv.invoice_number;

    const dt = inv.paid_at || inv.created_at ? new Date(inv.paid_at || inv.created_at) : new Date();
    const dateFormatted = dt.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' });
    const sym = inv.currency === 'INR' ? '₹' : '$';
    const amountStr = `${sym}${inv.amount.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

    content.innerHTML = `
      <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 10px; padding: 18px; margin-bottom: 20px;">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px;">
          <div>
            <div style="font-size: 0.72rem; color: #94a3b8; text-transform: uppercase; font-weight: 600;">Invoice Reference</div>
            <div style="font-size: 1.15rem; font-weight: 800; color: #a5b4fc; font-family: monospace;">${inv.invoice_number}</div>
          </div>
          <div>
            <span class="status-badge status-badge-paid" style="font-size: 0.78rem; padding: 4px 10px;">${(inv.status || 'PAID').toUpperCase()}</span>
          </div>
        </div>

        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 0.8rem; margin-bottom: 14px; border-top: 1px solid rgba(255, 255, 255, 0.06); padding-top: 12px;">
          <div>
            <span style="color: #94a3b8;">Issue &amp; Payment Date:</span>
            <div style="color: #ffffff; font-weight: 600;">${dateFormatted}</div>
          </div>
          <div>
            <span style="color: #94a3b8;">Subscription Tier:</span>
            <div style="color: #ffffff; font-weight: 600;">${(inv.plan_id || 'pro').toUpperCase()} (${inv.billing_cycle || 'monthly'})</div>
          </div>
        </div>

        <div style="background: rgba(99, 102, 241, 0.08); border-radius: 8px; padding: 12px 14px; display: flex; justify-content: space-between; align-items: center;">
          <span style="font-weight: 600; color: #cbd5e1;">Total Amount Debited</span>
          <span style="font-size: 1.35rem; font-weight: 800; color: #34d399;">${amountStr}</span>
        </div>
      </div>

      <div style="margin-bottom: 20px;">
        <div style="font-size: 0.78rem; font-weight: 700; color: #cbd5e1; margin-bottom: 8px; text-transform: uppercase;">
          Gateway Transparency Verification Tokens
        </div>
        <div style="background: rgba(0, 0, 0, 0.3); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 8px; padding: 12px; font-family: monospace; font-size: 0.75rem; line-height: 1.6; color: #cbd5e1; word-break: break-all;">
          <div><strong style="color: #94a3b8;">Payment Gateway:</strong> Razorpay PCI-DSS Level 1</div>
          <div><strong style="color: #94a3b8;">Razorpay Payment ID:</strong> ${inv.razorpay_payment_id || '—'}</div>
          <div><strong style="color: #94a3b8;">Subscription Mandate ID:</strong> ${inv.razorpay_subscription_id || '—'}</div>
          <div><strong style="color: #94a3b8;">Gateway Invoice ID:</strong> ${inv.razorpay_invoice_id || '—'}</div>
          <div style="margin-top: 6px; color: #34d399; font-size: 0.72rem;">✓ Verified &bull; Zero sensitive cardholder data handled or saved</div>
        </div>
      </div>

      <div style="display: flex; gap: 10px; justify-content: flex-end;">
        <button type="button" class="btn btn-outline" onclick="window.print()" style="padding: 8px 16px; border-radius: 8px; font-size: 0.82rem; cursor: pointer;">
          🖨️ Print Receipt
        </button>
        <button type="button" class="card-cta-btn card-cta-primary" onclick="window.closeInvoiceDetail()" style="width: auto; padding: 8px 18px; font-size: 0.82rem;">
          Close
        </button>
      </div>
    `;

    modal.style.display = 'flex';
    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');
  };

  P.closeInvoiceDetail = function () {
    const modal = document.getElementById('invoice-detail-modal');
    if (!modal) return;
    modal.style.display = 'none';
    modal.classList.remove('active');
    modal.setAttribute('aria-hidden', 'true');
  };
})(window);
