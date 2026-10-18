/**
 * Room Workspaces, Database Reference Previews & Multi-File Scoping
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  async function loadRooms() {
    const tabRoomsBadge = document.getElementById('tab-rooms-badge');
    const roomsList = document.getElementById('rooms-list');
    const currentUser = API.getCurrentUser();

    if (!currentUser) {
      RAG.state.rooms = [];
      RAG.state.currentRoomId = null;
      RAG.state.currentRoom = null;
      if (tabRoomsBadge) tabRoomsBadge.textContent = '0';
      if (roomsList) {
        roomsList.innerHTML = `
          <div style="text-align: center; padding: 32px 14px; color: var(--text-muted); font-size: 0.82rem;">
            <div style="font-size: 2rem; margin-bottom: 8px;">🏠</div>
            <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 6px;">Sign in to access workspaces</div>
            <div style="font-size: 0.75rem; line-height: 1.4; margin-bottom: 14px; color: var(--text-secondary);">Organize and scope files into isolated rooms for grounded multi-document Q&amp;A.</div>
            <button class="btn btn-primary" style="font-size: 0.75rem; padding: 6px 14px;" onclick="window.showAuthModal ? window.showAuthModal('signin') : (window.switchAuthTab?.('signin'), document.getElementById('auth-modal')?.classList.add('active'))">
              Sign In / Register
            </button>
          </div>
        `;
      }
      return;
    }

    try {
      const data = await API.getRooms();
      RAG.state.rooms = data || [];
      if (tabRoomsBadge) tabRoomsBadge.textContent = RAG.state.rooms.length;

      // If no rooms exist, automatically create default General Workspace
      if (RAG.state.rooms.length === 0) {
        try {
          const defaultRoom = await API.createRoom('General Workspace', 'Default workspace for uploaded documents');
          RAG.state.rooms = [defaultRoom];
          if (tabRoomsBadge) tabRoomsBadge.textContent = 1;
        } catch (e) {
          console.warn('Auto room creation error:', e);
        }
      }

      renderRoomsList();

      // Ensure active room is selected and restored
      if (!RAG.state.currentRoomId || !RAG.state.rooms.find((r) => r.id === RAG.state.currentRoomId)) {
        if (RAG.state.rooms.length > 0) {
          selectRoom(RAG.state.rooms[0].id, false);
        }
      } else {
        selectRoom(RAG.state.currentRoomId, false);
      }
    } catch (err) {
      console.error('Failed to load rooms:', err);
    }
  }

  function renderRoomsList() {
    const roomsList = document.getElementById('rooms-list');
    if (!roomsList) return;
    if (!RAG.state.rooms || RAG.state.rooms.length === 0) {
      roomsList.innerHTML = `
        <div style="text-align: center; padding: 24px 10px; color: var(--text-muted); font-size: 0.82rem;">
          No workspaces yet.<br>Click "+ New Room" above to create one.
        </div>
      `;
      return;
    }

    roomsList.innerHTML = RAG.state.rooms
      .map((r) => {
        const isActive = r.id === RAG.state.currentRoomId;
        const privacyBadge = r.is_public
          ? `<span class="badge-pill" style="font-size: 0.62rem; background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);">🌐 Public</span>`
          : `<span class="badge-pill" style="font-size: 0.62rem; background: rgba(107, 114, 128, 0.15); color: #9ca3af; border: 1px solid rgba(107, 114, 128, 0.3);">🔒 Private</span>`;
        const roleBadge = r.user_role
          ? `<span class="badge-pill" style="font-size: 0.62rem; background: rgba(99, 102, 241, 0.15); color: #818cf8; text-transform: capitalize;">${r.user_role}</span>`
          : '';

        return `
          <div class="room-card ${isActive ? 'active' : ''}" onclick="window.selectRoom('${r.id}', true)">
            <div class="room-card-header">
              <span class="room-title" title="${RAG.utils.escapeHtml(r.name)}">${RAG.utils.escapeHtml(r.name)}</span>
              ${isActive ? '<span class="room-badge-active">ACTIVE</span>' : ''}
            </div>
            ${r.description ? `<div class="room-desc">${RAG.utils.escapeHtml(r.description)}</div>` : ''}
            <div class="room-meta" style="flex-wrap: wrap; gap: 6px;">
              <span>📁 ${r.document_count || 0} files • 💬 ${r.message_count || 0} msgs</span>
              ${privacyBadge}
              ${roleBadge}
              <div class="room-actions">
                <button class="room-action-btn" type="button" onclick="event.stopPropagation(); event.preventDefault(); window.openShareRoomModal('${r.id}')" title="Workspace Sharing & Members Access (RBAC)">👥</button>
                <button class="room-action-btn" type="button" onclick="event.stopPropagation(); event.preventDefault(); window.deleteRoom('${r.id}', event)" title="Delete Room">🗑️</button>
              </div>
            </div>
          </div>
        `;
      })
      .join('');
  }

  async function selectRoom(roomId, switchTab = false) {
    RAG.state.currentRoomId = roomId;
    API.setActiveRoomId(roomId);
    RAG.utils.closeMobileSidebar();

    // Update URL without page reload
    const url = new URL(window.location);
    url.searchParams.set('room', roomId);
    window.history.replaceState({}, '', url);

    renderRoomsList();

    const bannerRoomName = document.getElementById('banner-room-name');
    const convTitle = document.getElementById('conv-title');
    const convSubtitle = document.getElementById('conv-subtitle');
    const bannerRoomFiles = document.getElementById('banner-room-files');

    try {
      const room = await API.getRoom(roomId);
      RAG.state.currentRoom = room;

      if (bannerRoomName) bannerRoomName.textContent = room.name;
      if (convTitle) convTitle.textContent = room.name;
      if (convSubtitle) convSubtitle.textContent = room.description || 'Strictly grounded answers with verifiable source attribution';

      const bannerRoomPrivacy = document.getElementById('banner-room-privacy');
      if (bannerRoomPrivacy) {
        bannerRoomPrivacy.textContent = room.is_public ? '🌐 Public' : '🔒 Private';
        bannerRoomPrivacy.style.color = room.is_public ? '#34d399' : '#9ca3af';
        bannerRoomPrivacy.style.background = room.is_public ? 'rgba(16, 185, 129, 0.15)' : 'rgba(107, 114, 128, 0.15)';
      }

      if (bannerRoomFiles) {
        if (!room.documents || room.documents.length === 0) {
          bannerRoomFiles.innerHTML = `<span class="room-files-empty-pill"><span>📎</span><span>No files attached</span></span>`;
        } else {
          bannerRoomFiles.innerHTML = room.documents
            .map(
              (d) => `
              <span class="room-file-pill" title="${RAG.utils.escapeHtml(d.filename)} (${d.chunk_count} chunks)">
                <span>${RAG.utils.iconMap[d.file_type] || '📄'}</span>
                <span>${RAG.utils.escapeHtml(d.filename)}</span>
                <span style="opacity: 0.6; cursor: pointer;" onclick="window.detachDocFromRoom('${room.id}', '${d.id}', event)" title="Detach file from room">×</span>
              </span>
            `
            )
            .join('');
        }
      }

      renderRoomReferences(room.references || []);

      RAG.state.currentConversationId = room.active_conversation_id;
      if (RAG.state.currentConversationId) {
        localStorage.setItem('rag_active_conv_id', RAG.state.currentConversationId);
        if (RAG.chat?.loadConversationMessages) {
          RAG.chat.loadConversationMessages(RAG.state.currentConversationId);
        }
      } else {
        if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
      }

      if (RAG.history?.loadConversations) RAG.history.loadConversations();
    } catch (err) {
      console.error('Error fetching room details:', err);
    }
  }

  function renderRoomReferences(refs) {
    const refCountBadge = document.getElementById('ref-count-badge');
    const refCardsGrid = document.getElementById('ref-cards-grid');

    if (refCountBadge) refCountBadge.textContent = refs ? refs.length : 0;
    if (!refCardsGrid) return;

    if (!refs || refs.length === 0) {
      refCardsGrid.innerHTML = `
        <div style="grid-column: 1/-1; text-align: center; color: var(--text-muted); font-size: 0.75rem; padding: 16px;">
          No indexed references available yet. Upload or attach documents to extract instant context highlights.
        </div>
      `;
      return;
    }

    refCardsGrid.innerHTML = refs
      .map(
        (ref) => `
        <div class="ref-card" onclick="window.usePrompt('Summarize key details from ${RAG.utils.escapeHtml(ref.filename)} regarding: ${RAG.utils.escapeHtml(ref.excerpt).replace(/'/g, "\\'")}')" title="Click to ask question about this reference">
          <div class="ref-card-header">
            <span>📄 ${RAG.utils.escapeHtml(ref.filename)}</span>
            <span>p. ${ref.page || 1}</span>
          </div>
          <div class="ref-card-snippet">
            ${RAG.utils.escapeHtml(ref.excerpt)}
          </div>
        </div>
      `
      )
      .join('');
  }

  let activeShareRoomId = null;

  async function openShareRoomModal(roomId) {
    activeShareRoomId = roomId;
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

  async function deleteRoom(roomId, ev) {
    if (ev) {
      ev.stopPropagation();
      ev.preventDefault();
    }
    const r = (RAG.state.rooms || []).find((x) => x.id === roomId);
    const rName = r ? r.name : 'Workspace Room';
    const docCount = r ? (r.document_count || 0) : 0;
    const msgCount = r ? (r.message_count || 0) : 0;

    RAG.utils.showConfirmModal({
      title: 'Delete Room Workspace',
      headerIcon: '🗑️',
      itemIcon: '🏛️',
      itemName: rName,
      itemMeta: `${docCount} files • ${msgCount} msgs`,
      prompt: `Are you sure you want to delete "${rName}"? All room document links and discussion thread messages will be permanently deleted.`,
      confirmText: 'Delete Room',
      onConfirm: async () => {
        try {
          await API.deleteRoom(roomId);
          RAG.utils.showToast('Room deleted successfully', 'info');
          if (RAG.state.currentRoomId === roomId) {
            RAG.state.currentRoomId = null;
            API.setActiveRoomId(null);
            const url = new URL(window.location);
            url.searchParams.delete('room');
            window.history.replaceState({}, '', url);

            const bannerRoomName = document.getElementById('banner-room-name');
            const convTitle = document.getElementById('conv-title');
            const convSubtitle = document.getElementById('conv-subtitle');
            const bannerRoomFiles = document.getElementById('banner-room-files');
            if (bannerRoomName) bannerRoomName.textContent = 'General Workspace';
            if (convTitle) convTitle.textContent = 'AI Intelligence Workspace';
            if (convSubtitle) convSubtitle.textContent = 'Select or create a workspace room to start collaborating';
            if (bannerRoomFiles) bannerRoomFiles.innerHTML = `<span class="room-files-empty-pill"><span>📎</span><span>No files attached</span></span>`;
            if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
          }
          await loadRooms();
        } catch (err) {
          RAG.utils.showToast(err.message, 'error');
        }
      },
    });
  }

  async function detachDocFromRoom(roomId, docId, ev) {
    if (ev) ev.stopPropagation();
    try {
      await API.detachDocumentFromRoom(roomId, docId);
      RAG.utils.showToast('Document detached from room', 'info');
      selectRoom(roomId, false);
    } catch (err) {
      RAG.utils.showToast(err.message, 'error');
    }
  }

  function initRoomListeners() {
    const createRoomBtn = document.getElementById('create-room-btn');
    const roomModal = document.getElementById('room-modal');
    const closeRoomBtn = document.getElementById('close-room-btn');
    const cancelRoomBtn = document.getElementById('cancel-room-btn');
    const createRoomForm = document.getElementById('create-room-form');
    const roomNameInput = document.getElementById('room-name-input');
    const roomDescInput = document.getElementById('room-desc-input');
    const createRoomPublicCheckbox = document.getElementById('create-room-public');
    const roomDocCheckboxes = document.getElementById('room-doc-checkboxes');
    const toggleReferencesBtn = document.getElementById('toggle-references-btn');
    const roomReferencesDrawer = document.getElementById('room-references-drawer');
    const attachFileRoomBtn = document.getElementById('attach-file-room-btn');
    const shareRoomBtn = document.getElementById('share-room-btn');
    const shareRoomModal = document.getElementById('share-room-modal');
    const closeShareRoomBtn = document.getElementById('close-share-room-btn');
    const doneShareRoomBtn = document.getElementById('done-share-room-btn');
    const roomIsPublicCheckbox = document.getElementById('room-is-public-checkbox');
    const addRoomMemberForm = document.getElementById('add-room-member-form');
    const fileInput = document.getElementById('file-input');

    toggleReferencesBtn?.addEventListener('click', () => {
      if (!roomReferencesDrawer) return;
      const isHidden = roomReferencesDrawer.style.display === 'none';
      roomReferencesDrawer.style.display = isHidden ? 'block' : 'none';
    });

    attachFileRoomBtn?.addEventListener('click', () => {
      const currentUser = API.getCurrentUser();
      if (!currentUser) {
        if (RAG.auth?.showAuthModal) {
          RAG.auth.showAuthModal('signin', 'Authentication required to attach files to a room.');
        } else {
          const authModal = document.getElementById('auth-modal');
          if (authModal) authModal.classList.add('active');
        }
        return;
      }
      if (RAG.app?.switchSidebarTab) RAG.app.switchSidebarTab('docs');
      fileInput?.click();
    });

    shareRoomBtn?.addEventListener('click', () => {
      if (RAG.state.currentRoomId) {
        openShareRoomModal(RAG.state.currentRoomId);
      } else {
        RAG.utils.showToast('Please select a workspace first.', 'info');
      }
    });

    const closeShareModal = () => shareRoomModal?.classList.remove('active');
    closeShareRoomBtn?.addEventListener('click', closeShareModal);
    doneShareRoomBtn?.addEventListener('click', closeShareModal);

    roomIsPublicCheckbox?.addEventListener('change', async (e) => {
      if (!activeShareRoomId) return;
      const isPublic = e.target.checked;
      try {
        await API.shareRoom(activeShareRoomId, isPublic);
        RAG.utils.showToast(isPublic ? 'Workspace is now Public to all users.' : 'Workspace is now Private.', 'success');
        await loadRooms();
        if (RAG.state.currentRoomId === activeShareRoomId) {
          selectRoom(activeShareRoomId, false);
        }
      } catch (err) {
        e.target.checked = !isPublic;
        RAG.utils.showToast(err.message || 'Failed to update workspace sharing', 'error');
      }
    });

    const memberIdInput = document.getElementById('member-identifier-input');
    if (memberIdInput && RAG.validator) {
      RAG.validator.attachLiveValidation(memberIdInput, RAG.validator.validateMemberIdentifier);
    }

    addRoomMemberForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!activeShareRoomId) return;
      const idInput = document.getElementById('member-identifier-input');
      const roleSelect = document.getElementById('member-role-select');
      const identifier = idInput?.value.trim() || '';
      const role = roleSelect?.value || 'viewer';

      if (RAG.validator) {
        const idErr = RAG.validator.validateMemberIdentifier(identifier);
        if (idErr) {
          RAG.validator.showError(idInput, idErr);
          idInput?.focus();
          return;
        } else {
          RAG.validator.clearError(idInput);
        }
      }

      try {
        await API.addRoomMember(activeShareRoomId, identifier, role);
        RAG.utils.showToast(`User '${identifier}' added as ${role}!`, 'success');
        if (idInput) {
          idInput.value = '';
          if (RAG.validator) RAG.validator.clearError(idInput);
        }
        const updatedRoom = await API.getRoom(activeShareRoomId);
        renderRoomMembers(updatedRoom.members || [], updatedRoom);
      } catch (err) {
        if (idInput && RAG.validator) {
          RAG.validator.showError(idInput, err.message);
        }
        RAG.utils.showToast(err.message || 'Failed to add member', 'error');
      }
    });

    if (RAG.validator) {
      if (roomNameInput) RAG.validator.attachLiveValidation(roomNameInput, RAG.validator.validateRoomName);
      if (roomDescInput) RAG.validator.attachLiveValidation(roomDescInput, RAG.validator.validateRoomDescription);
    }

    createRoomBtn?.addEventListener('click', () => {
      const currentUser = API.getCurrentUser();
      if (!currentUser) {
        if (RAG.auth?.showAuthModal) {
          RAG.auth.showAuthModal('signin', 'Authentication required to create a workspace room.');
        } else {
          const authModal = document.getElementById('auth-modal');
          if (authModal) authModal.classList.add('active');
        }
        return;
      }
      if (RAG.validator) {
        if (roomNameInput) RAG.validator.clearError(roomNameInput);
        if (roomDescInput) RAG.validator.clearError(roomDescInput);
      }
      if (roomDocCheckboxes) {
        if (!RAG.state.activeDocuments || RAG.state.activeDocuments.length === 0) {
          roomDocCheckboxes.innerHTML = `<span style="font-size: 0.75rem; color: var(--text-muted);">No indexed documents in library yet.</span>`;
        } else {
          roomDocCheckboxes.innerHTML = RAG.state.activeDocuments
            .map(
              (d) => `
              <label style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 0.78rem; cursor: pointer; color: var(--text-primary);">
                <input type="checkbox" name="room_docs" value="${d.id}" checked>
                <span>${RAG.utils.iconMap[d.file_type] || '📄'} ${RAG.utils.escapeHtml(d.filename)} (${d.chunk_count} chunks)</span>
              </label>
            `
            )
            .join('');
        }
      }
      roomModal?.classList.add('active');
    });

    const resetRoomModalErrors = () => {
      if (RAG.validator) {
        if (roomNameInput) RAG.validator.clearError(roomNameInput);
        if (roomDescInput) RAG.validator.clearError(roomDescInput);
      }
      roomModal?.classList.remove('active');
    };

    closeRoomBtn?.addEventListener('click', resetRoomModalErrors);
    cancelRoomBtn?.addEventListener('click', resetRoomModalErrors);

    createRoomForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = roomNameInput?.value.trim() || '';
      const desc = roomDescInput?.value.trim() || '';
      const isPublic = createRoomPublicCheckbox?.checked || false;

      // JavaScript Input Validation
      if (RAG.validator) {
        const nameErr = RAG.validator.validateRoomName(name);
        if (nameErr) {
          RAG.validator.showError(roomNameInput, nameErr);
          roomNameInput?.focus();
          return;
        } else {
          RAG.validator.clearError(roomNameInput);
        }

        const descErr = RAG.validator.validateRoomDescription(desc);
        if (descErr) {
          RAG.validator.showError(roomDescInput, descErr);
          roomDescInput?.focus();
          return;
        } else {
          RAG.validator.clearError(roomDescInput);
        }
      }

      try {
        RAG.utils.showToast('Creating workspace room...', 'info');
        const room = await API.createRoom(name, desc, isPublic);

        const checked = roomDocCheckboxes?.querySelectorAll('input[name="room_docs"]:checked');
        if (checked && checked.length > 0) {
          await Promise.all(Array.from(checked).map((input) => API.attachDocumentToRoom(room.id, input.value).catch(() => {})));
        }

        RAG.utils.showToast(`Room '${name}' created!`, 'success');
        resetRoomModalErrors();
        createRoomForm.reset();
        await loadRooms();
        selectRoom(room.id, true);
      } catch (err) {
        if (roomNameInput && RAG.validator) {
          RAG.validator.showError(roomNameInput, err.message);
        }
        RAG.utils.showToast(err.message, 'error');
      }
    });
  }

  RAG.rooms = {
    loadRooms,
    renderRoomsList,
    selectRoom,
    deleteRoom,
    detachDocFromRoom,
    openShareRoomModal,
    removeRoomMember,
    init: initRoomListeners,
  };

  global.loadRooms = loadRooms;
  global.selectRoom = selectRoom;
  global.deleteRoom = deleteRoom;
  global.detachDocFromRoom = detachDocFromRoom;
  global.openShareRoomModal = openShareRoomModal;
  global.removeRoomMember = removeRoomMember;
})(window);
