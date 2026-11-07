/**
 * Room Members, Role-Based Access Control (RBAC), Share Link Revocation & PII Breach Protection Modals
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.rooms = RAG.rooms || {};

  let activeShareRoomId = null;

  async function openShareRoomModal(roomId) {
    activeShareRoomId = roomId;
    RAG.rooms.activeShareRoomId = roomId;
    const modal = document.getElementById('share-room-modal');
    const title = document.getElementById('share-room-title');
    const publicCheckbox = document.getElementById('room-is-public-checkbox');
    const shareUrlInput = document.getElementById('room-share-url-input');
    const shareStatusBadge = document.getElementById('share-link-status-badge');

    if (!modal) return;
    modal.classList.add('active');

    try {
      const room = await API.getRoom(roomId);
      if (title) title.textContent = `Share "${room.name}"`;
      if (publicCheckbox) {
        publicCheckbox.checked = !!room.is_public;
      }

      // Generate or retrieve share link
      try {
        const linkData = await API.generateShareLink(roomId);
        if (shareUrlInput) shareUrlInput.value = linkData.share_url;
        if (shareStatusBadge) {
          if (linkData.is_revoked) {
            shareStatusBadge.textContent = 'Revoked';
            shareStatusBadge.style.color = '#ef4444';
            shareStatusBadge.style.background = 'rgba(239, 68, 68, 0.15)';
          } else {
            shareStatusBadge.textContent = 'Active';
            shareStatusBadge.style.color = '#34d399';
            shareStatusBadge.style.background = 'rgba(16, 185, 129, 0.15)';
          }
        }
      } catch (linkErr) {
        if (shareUrlInput) shareUrlInput.value = window.location.origin + `/shared/room/${roomId}`;
      }

      // Scan for PII Breaches
      await scanPIIForModal(roomId);

      renderRoomMembers(room.members || [], room);
    } catch (err) {
      RAG.utils.showToast(err.message || 'Failed to load workspace details', 'error');
    }
  }

  async function scanPIIForModal(roomId) {
    const alertBox = document.getElementById('pii-alert-box');
    const previewContainer = document.getElementById('pii-mask-preview-container');
    const previewBox = document.getElementById('pii-mask-preview');
    const consentActions = document.getElementById('pii-consent-actions');

    try {
      const scan = await API.scanRoomPII(roomId);
      if (scan.has_pii_breach) {
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.innerHTML = `
            <strong>⚠️ Privacy Alert (Breach Detected):</strong> Found ${scan.breach_count} sensitive item(s) (${scan.detected_categories.join(', ')}).
            To prevent data leakage, personal information has been contextually masked.
          `;
        }
        if (previewContainer && previewBox) {
          previewContainer.style.display = 'block';
          previewBox.textContent = scan.preview_masked_snippets.length > 0
            ? scan.preview_masked_snippets.join('\n')
            : '(*****, [Sensitive Personal Information Detected])';
        }
        if (consentActions) {
          consentActions.style.display = 'block';
        }
      } else {
        if (alertBox) {
          alertBox.style.display = 'block';
          alertBox.style.background = 'rgba(16, 185, 129, 0.1)';
          alertBox.style.borderLeftColor = '#10b981';
          alertBox.style.color = '#34d399';
          alertBox.innerHTML = '✅ No personal data (PII) breaches detected in this workspace.';
        }
        if (previewContainer) previewContainer.style.display = 'none';
        if (consentActions) consentActions.style.display = 'none';
      }
    } catch (err) {
      console.warn('PII scan note:', err);
    }
  }

  async function revokeShareLink() {
    if (!activeShareRoomId) return;
    try {
      await API.revokeShareLink(activeShareRoomId);
      const shareStatusBadge = document.getElementById('share-link-status-badge');
      if (shareStatusBadge) {
        shareStatusBadge.textContent = 'Revoked';
        shareStatusBadge.style.color = '#ef4444';
        shareStatusBadge.style.background = 'rgba(239, 68, 68, 0.15)';
      }
      const publicCheckbox = document.getElementById('room-is-public-checkbox');
      if (publicCheckbox) publicCheckbox.checked = false;

      RAG.utils.showToast('Share link revoked immediately. External access terminated.', 'info');
      await RAG.rooms.loadRooms();
    } catch (err) {
      RAG.utils.showToast(err.message || 'Failed to revoke share link', 'error');
    }
  }

  async function submitConsent(mode) {
    if (!activeShareRoomId) return;
    if (mode === 'unmasked') {
      const confirmed = confirm(
        'SECURITY WARNING: You are consenting to make sensitive personal information unmasked to other users. Are you sure you wish to proceed?'
      );
      if (!confirmed) return;
    }

    try {
      const res = await API.submitPIIConsent(activeShareRoomId, mode, true);
      RAG.utils.showToast(res.message, 'success');
      await scanPIIForModal(activeShareRoomId);
    } catch (err) {
      RAG.utils.showToast(err.message || 'Failed to record consent', 'error');
    }
  }

  function renderRoomMembers(members, room) {
    const membersList = document.getElementById('room-members-list');
    if (!membersList) return;

    const currentUser = API.getCurrentUser();
    const canManage = currentUser && (currentUser.id === room.user_id || currentUser.role === 'admin');

    if (!members || members.length === 0) {
      membersList.innerHTML = `
        <div style="text-align: center; color: var(--text-muted); font-size: 0.78rem; padding: 14px;">
          No invited members yet. Invite team members above to grant private access.
        </div>
      `;
      return;
    }

    membersList.innerHTML = members
      .map(
        (m) => `
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; border-bottom: 1px solid var(--border-color); font-size: 0.8rem;">
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="background: rgba(99, 102, 241, 0.2); color: #818cf8; width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-weight: 600; font-size: 0.7rem;">
              ${(m.username || 'U').charAt(0).toUpperCase()}
            </span>
            <div>
              <span style="font-weight: 600; color: var(--text-primary);">${RAG.utils.escapeHtml(m.username)}</span>
              <span style="font-size: 0.72rem; color: var(--text-muted); margin-left: 4px;">(${RAG.utils.escapeHtml(m.email)})</span>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 8px;">
            <span class="badge-pill" style="font-size: 0.65rem; background: rgba(99, 102, 241, 0.15); color: #818cf8; text-transform: capitalize;">
              ${m.role}
            </span>
            ${
              canManage
                ? `<button type="button" class="doc-btn delete" style="padding: 2px 6px; font-size: 0.75rem;" onclick="window.removeRoomMember('${room.id}', '${m.user_id}')" title="Remove member">✕</button>`
                : ''
            }
          </div>
        </div>
      `
      )
      .join('');
  }

  async function removeRoomMember(roomId, userId) {
    try {
      await API.removeRoomMember(roomId, userId);
      RAG.utils.showToast('Member removed from room', 'info');
      const updatedRoom = await API.getRoom(roomId);
      renderRoomMembers(updatedRoom.members || [], updatedRoom);
    } catch (err) {
      RAG.utils.showToast(err.message || 'Failed to remove member', 'error');
    }
  }

  // Bind modal buttons
  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('revoke-share-link-btn')?.addEventListener('click', revokeShareLink);
    document.getElementById('copy-share-link-btn')?.addEventListener('click', () => {
      const input = document.getElementById('room-share-url-input');
      if (input && input.value) {
        navigator.clipboard.writeText(input.value).then(() => {
          RAG.utils.showToast('Share link copied to clipboard', 'info');
        }).catch(() => {
          input.select();
          document.execCommand('copy');
          RAG.utils.showToast('Share link copied', 'info');
        });
      }
    });
    document.getElementById('scan-pii-btn')?.addEventListener('click', () => {
      if (activeShareRoomId) scanPIIForModal(activeShareRoomId);
    });
    document.getElementById('consent-mask-btn')?.addEventListener('click', () => submitConsent('mask'));
    document.getElementById('consent-unmask-btn')?.addEventListener('click', () => submitConsent('unmasked'));
  });

  RAG.rooms.openShareRoomModal = openShareRoomModal;
  RAG.rooms.renderRoomMembers = renderRoomMembers;
  RAG.rooms.removeRoomMember = removeRoomMember;
  RAG.rooms.revokeShareLink = revokeShareLink;
  RAG.rooms.submitConsent = submitConsent;
  RAG.rooms.getActiveShareRoomId = () => activeShareRoomId;
  window.openShareRoomModal = openShareRoomModal;
  window.removeRoomMember = removeRoomMember;
})(window);
