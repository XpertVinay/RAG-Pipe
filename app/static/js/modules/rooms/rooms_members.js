/**
 * Room Members, Role-Based Access Control (RBAC) & Sharing Modals
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

    if (!modal) return;
    modal.classList.add('active');

    try {
      const room = await API.getRoom(roomId);
      if (title) title.textContent = `Share "${room.name}"`;
      if (publicCheckbox) {
        publicCheckbox.checked = !!room.is_public;
      }
      renderRoomMembers(room.members || [], room);
    } catch (err) {
      RAG.utils.showToast(err.message || 'Failed to load workspace details', 'error');
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

  RAG.rooms.openShareRoomModal = openShareRoomModal;
  RAG.rooms.renderRoomMembers = renderRoomMembers;
  RAG.rooms.removeRoomMember = removeRoomMember;
  RAG.rooms.getActiveShareRoomId = () => activeShareRoomId;
})(window);
