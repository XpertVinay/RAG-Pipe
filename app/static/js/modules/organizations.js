/**
 * Organization and Multi-User Team Invites Module
 */

(function () {
  let activeInvites = [];
  let currentOrg = null;

  function initOrganizations() {
    setupOrgModal();
    setupInviteCreation();
    checkUrlForInvite();
    window.addEventListener('auth:login', onUserLogin);
    window.addEventListener('auth:logout', onUserLogout);

    // Initial check if user is already logged in
    if (window.currentUser) {
      onUserLogin({ detail: { user: window.currentUser } });
    }
  }

  function setupOrgModal() {
    const openBtn = document.getElementById('open-org-btn');
    const modal = document.getElementById('org-modal');
    const closeBtn = document.getElementById('close-org-modal-btn');
    const refreshBtn = document.getElementById('refresh-invites-btn');
    const copyNewBtn = document.getElementById('copy-new-invite-btn');

    if (openBtn && modal) {
      openBtn.addEventListener('click', () => {
        openOrgDashboard();
      });
    }

    if (closeBtn && modal) {
      closeBtn.addEventListener('click', () => {
        modal.classList.remove('active');
        modal.setAttribute('aria-hidden', 'true');
      });
    }

    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) {
          modal.classList.remove('active');
          modal.setAttribute('aria-hidden', 'true');
        }
      });
    }

    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => {
        loadInvites();
      });
    }

    if (copyNewBtn) {
      copyNewBtn.addEventListener('click', () => {
        const input = document.getElementById('new-invite-url-input');
        if (input && input.value) {
          navigator.clipboard.writeText(input.value).then(() => {
            if (window.showToast) window.showToast('Invite link copied to clipboard!', 'success');
          });
        }
      });
    }
  }

  async function openOrgDashboard() {
    const modal = document.getElementById('org-modal');
    if (!modal) return;

    modal.classList.add('active');
    modal.setAttribute('aria-hidden', 'false');

    await Promise.all([loadCurrentOrg(), loadInvites()]);
  }

  async function loadCurrentOrg() {
    const token = localStorage.getItem('rag_access_token');
    if (!token) return;

    try {
      const res = await fetch('/api/org/current', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        currentOrg = await res.json();
        renderOrgHeader(currentOrg);
      }
    } catch (err) {
      console.warn('Failed to load organization:', err);
    }
  }

  function renderOrgHeader(org) {
    const nameEl = document.getElementById('org-name-display');
    const badgeEl = document.getElementById('org-plan-badge');
    const seatsEl = document.getElementById('org-seats-count');

    if (nameEl) nameEl.textContent = org.name;
    if (badgeEl) {
      badgeEl.textContent = org.plan_tier.toUpperCase();
      if (org.plan_tier === 'pro') {
        badgeEl.style.background = 'rgba(99, 102, 241, 0.25)';
        badgeEl.style.color = '#a5b4fc';
      } else if (org.plan_tier === 'enterprise') {
        badgeEl.style.background = 'rgba(16, 185, 129, 0.25)';
        badgeEl.style.color = '#34d399';
      }
    }
    if (seatsEl) seatsEl.textContent = `${org.member_count} / ${org.max_seats}`;
  }

  async function loadInvites() {
    const token = localStorage.getItem('rag_access_token');
    const container = document.getElementById('invites-list-container');
    if (!token || !container) return;

    container.innerHTML = '<div style="text-align: center; padding: 16px; color: var(--text-muted); font-size: 0.8rem;">Loading invitation links...</div>';

    try {
      const res = await fetch('/api/org/invites', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Failed to load invites');

      activeInvites = await res.json();
      renderInvitesList(activeInvites);
    } catch (err) {
      container.innerHTML = `<div style="text-align: center; padding: 16px; color: var(--status-failed); font-size: 0.8rem;">${err.message}</div>`;
    }
  }

  function renderInvitesList(invites) {
    const container = document.getElementById('invites-list-container');
    if (!container) return;

    if (!invites || invites.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 24px 10px; color: var(--text-muted); font-size: 0.82rem; background: rgba(255,255,255,0.02); border-radius: 6px;">
          No invitation links generated yet. Create one above to invite team members with specific roles!
        </div>
      `;
      return;
    }

    container.innerHTML = invites.map(inv => {
      const isExpired = new Date(inv.expires_at) < new Date();
      let statusBadge = '<span class="badge-pill" style="font-size: 0.65rem; background: rgba(16,185,129,0.2); color: #34d399;">Active</span>';
      if (inv.is_used) {
        statusBadge = '<span class="badge-pill" style="font-size: 0.65rem; background: rgba(107,114,128,0.2); color: #9ca3af;">Redeemed</span>';
      } else if (isExpired) {
        statusBadge = '<span class="badge-pill" style="font-size: 0.65rem; background: rgba(239,68,68,0.2); color: #f87171;">Expired</span>';
      }

      const roleColors = {
        admin: 'background: rgba(239, 68, 68, 0.2); color: #fca5a5;',
        staff: 'background: rgba(99, 102, 241, 0.2); color: #a5b4fc;',
        user: 'background: rgba(107, 114, 128, 0.2); color: #cbd5e1;'
      };

      const roleBadge = `<span class="badge-pill" style="font-size: 0.68rem; text-transform: uppercase; ${roleColors[inv.assigned_role] || ''}">${inv.assigned_role}</span>`;
      const targetEmail = inv.email ? `<span style="color: var(--text-muted); font-size: 0.75rem;">🔒 Bound to: <strong>${inv.email}</strong></span>` : '<span style="color: var(--text-muted); font-size: 0.75rem;">🌐 Open Link</span>';
      const expDate = new Date(inv.expires_at).toLocaleDateString();

      return `
        <div style="background: rgba(255, 255, 255, 0.03); border: 1px solid var(--border-color); border-radius: 8px; padding: 12px 14px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;">
          <div style="display: flex; flex-direction: column; gap: 4px;">
            <div style="display: flex; align-items: center; gap: 8px;">
              ${roleBadge}
              ${statusBadge}
              ${targetEmail}
            </div>
            <div style="font-size: 0.72rem; color: var(--text-muted);">
              Expires: ${expDate} &bull; Created: ${new Date(inv.created_at).toLocaleDateString()}
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 6px;">
            ${!inv.is_used && !isExpired ? `
              <button class="btn btn-outline" style="font-size: 0.72rem; padding: 4px 8px;" onclick="window.copyInviteUrl('${inv.invite_url}')" title="Copy shareable link">
                📋 Copy
              </button>
            ` : ''}
            <button class="btn btn-outline" style="font-size: 0.72rem; padding: 4px 8px; color: var(--status-failed);" onclick="window.revokeInvite('${inv.id}')" title="Revoke link">
              🗑 Revoke
            </button>
          </div>
        </div>
      `;
    }).join('');
  }

  window.copyInviteUrl = function (url) {
    navigator.clipboard.writeText(url).then(() => {
      if (window.showToast) window.showToast('Invite link copied to clipboard!', 'success');
    });
  };

  window.revokeInvite = async function (inviteId) {
    if (!confirm('Are you sure you want to revoke this invitation link?')) return;

    const token = localStorage.getItem('rag_access_token');
    try {
      const res = await fetch(`/api/org/invites/${inviteId}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (!res.ok) throw new Error('Failed to revoke invite');

      if (window.showToast) window.showToast('Invite link revoked successfully.', 'info');
      await loadInvites();
    } catch (err) {
      if (window.showToast) window.showToast(err.message, 'error');
    }
  };

  function setupInviteCreation() {
    const form = document.getElementById('create-invite-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
      e.preventDefault();

      const roleSelect = document.getElementById('invite-role-select');
      const expirySelect = document.getElementById('invite-expiry-select');
      const emailInput = document.getElementById('invite-email-input');
      const submitBtn = document.getElementById('generate-invite-btn');

      const token = localStorage.getItem('rag_access_token');
      if (!token) return;

      try {
        if (submitBtn) submitBtn.disabled = true;

        const payload = {
          assigned_role: roleSelect.value,
          expires_in_days: parseInt(expirySelect.value, 10) || 7,
          email: emailInput.value.trim() || null
        };

        const res = await fetch('/api/org/invites', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify(payload)
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Failed to generate invitation link.');
        }

        // Show result box
        const resultBox = document.getElementById('new-invite-result-box');
        const urlInput = document.getElementById('new-invite-url-input');
        if (resultBox && urlInput) {
          urlInput.value = data.invite_url;
          resultBox.style.display = 'block';
        }

        if (window.showToast) {
          window.showToast(`Invite created for role: ${data.assigned_role.toUpperCase()}`, 'success');
        }

        // Refresh list
        await loadInvites();
      } catch (err) {
        if (window.showToast) window.showToast(err.message, 'error');
      } finally {
        if (submitBtn) submitBtn.disabled = false;
      }
    });
  }

  async function checkUrlForInvite() {
    const urlParams = new URLSearchParams(window.location.search);
    const inviteToken = urlParams.get('invite');
    if (!inviteToken) return;

    try {
      const res = await fetch(`/api/org/invites/verify/${inviteToken}`);
      const data = await res.json();

      if (!res.ok) {
        if (window.showToast) {
          window.showToast(data.detail || 'Invalid or expired invitation link.', 'error');
        }
        return;
      }

      // Valid invite! Save token globally
      window.activeInviteToken = inviteToken;

      // Open auth modal to Register tab
      const authModal = document.getElementById('auth-modal');
      const tabRegister = document.getElementById('auth-tab-register');
      const banner = document.getElementById('reg-invite-banner');
      const roleBadge = document.getElementById('invite-role-badge');
      const descText = document.getElementById('invite-desc-text');
      const emailInput = document.getElementById('reg-email');

      if (authModal) {
        authModal.classList.add('active');
        authModal.setAttribute('aria-hidden', 'false');
      }

      if (tabRegister) {
        tabRegister.click();
      }

      if (banner && roleBadge && descText) {
        roleBadge.textContent = data.assigned_role.toUpperCase();
        descText.textContent = `You were invited to join ${data.organization_name || 'the team'} with ${data.assigned_role.toUpperCase()} privileges.`;
        banner.style.display = 'block';
      }

      if (data.email && emailInput) {
        emailInput.value = data.email;
        emailInput.readOnly = true;
      }

      if (window.showToast) {
        window.showToast(`VIP Invite activated for role: ${data.assigned_role.toUpperCase()}`, 'success');
      }
    } catch (err) {
      console.warn('Invite check error:', err);
    }
  }

  function onUserLogin(e) {
    const user = e.detail?.user || window.currentUser;
    const orgBtn = document.getElementById('open-org-btn');
    if (orgBtn) {
      if (user && (user.role === 'admin' || user.role === 'super_admin' || user.role === 'superadmin')) {
        orgBtn.style.display = 'flex';
      } else {
        orgBtn.style.display = 'none';
      }
    }
  }

  function onUserLogout() {
    const orgBtn = document.getElementById('open-org-btn');
    if (orgBtn) orgBtn.style.display = 'none';
    currentOrg = null;
    activeInvites = [];
  }

  document.addEventListener('DOMContentLoaded', initOrganizations);
})();
