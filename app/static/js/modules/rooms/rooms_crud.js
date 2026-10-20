/**
 * Room Creation, Deletion, Document Detachment & Event Listeners
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.rooms = RAG.rooms || {};

  async function deleteRoom(roomId, ev) {
    if (ev) {
      ev.stopPropagation();
      ev.preventDefault();
    }
    const r = (RAG.state.rooms || []).find((x) => x.id === roomId);
    const rName = r ? r.name : 'Workspace Room';
    const docCount = r ? r.document_count || 0 : 0;
    const msgCount = r ? r.message_count || 0 : 0;

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
          await RAG.rooms.loadRooms();
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
      RAG.rooms.selectRoom(roomId, false);
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
        RAG.rooms.openShareRoomModal(RAG.state.currentRoomId);
      } else {
        RAG.utils.showToast('Please select a workspace first.', 'info');
      }
    });

    const closeShareModal = () => shareRoomModal?.classList.remove('active');
    closeShareRoomBtn?.addEventListener('click', closeShareModal);
    doneShareRoomBtn?.addEventListener('click', closeShareModal);

    roomIsPublicCheckbox?.addEventListener('change', async (e) => {
      const activeId = RAG.rooms.getActiveShareRoomId ? RAG.rooms.getActiveShareRoomId() : null;
      if (!activeId) return;
      const isPublic = e.target.checked;
      try {
        await API.shareRoom(activeId, isPublic);
        RAG.utils.showToast(isPublic ? 'Workspace is now Public to all users.' : 'Workspace is now Private.', 'success');
        await RAG.rooms.loadRooms();
        if (RAG.state.currentRoomId === activeId) {
          RAG.rooms.selectRoom(activeId, false);
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
      const activeId = RAG.rooms.getActiveShareRoomId ? RAG.rooms.getActiveShareRoomId() : null;
      if (!activeId) return;
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
        await API.addRoomMember(activeId, identifier, role);
        RAG.utils.showToast(`User '${identifier}' added as ${role}!`, 'success');
        if (idInput) {
          idInput.value = '';
          if (RAG.validator) RAG.validator.clearError(idInput);
        }
        const updatedRoom = await API.getRoom(activeId);
        RAG.rooms.renderRoomMembers(updatedRoom.members || [], updatedRoom);
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
        await RAG.rooms.loadRooms();
        RAG.rooms.selectRoom(room.id, true);
      } catch (err) {
        if (roomNameInput && RAG.validator) {
          RAG.validator.showError(roomNameInput, err.message);
        }
        RAG.utils.showToast(err.message, 'error');
      }
    });
  }

  RAG.rooms.deleteRoom = deleteRoom;
  RAG.rooms.detachDocFromRoom = detachDocFromRoom;
  RAG.rooms.init = initRoomListeners;
})(window);
