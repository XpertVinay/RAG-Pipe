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
        return `
          <div class="room-card ${isActive ? 'active' : ''}" onclick="window.selectRoom('${r.id}', true)">
            <div class="room-card-header">
              <span class="room-title" title="${RAG.utils.escapeHtml(r.name)}">${RAG.utils.escapeHtml(r.name)}</span>
              ${isActive ? '<span class="room-badge-active">ACTIVE</span>' : ''}
            </div>
            ${r.description ? `<div class="room-desc">${RAG.utils.escapeHtml(r.description)}</div>` : ''}
            <div class="room-meta">
              <span>📁 ${r.document_count || 0} files • 💬 ${r.message_count || 0} msgs</span>
              <div class="room-actions">
                <button class="room-action-btn" onclick="window.deleteRoom('${r.id}', event)" title="Delete Room">🗑️</button>
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

  async function deleteRoom(roomId, ev) {
    if (ev) ev.stopPropagation();
    if (!confirm('Are you sure you want to delete this workspace room?')) return;
    try {
      await API.deleteRoom(roomId);
      RAG.utils.showToast('Room deleted', 'info');
      RAG.state.currentRoomId = null;
      API.setActiveRoomId(null);
      loadRooms();
    } catch (err) {
      RAG.utils.showToast(err.message, 'error');
    }
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
    const roomDocCheckboxes = document.getElementById('room-doc-checkboxes');
    const toggleReferencesBtn = document.getElementById('toggle-references-btn');
    const roomReferencesDrawer = document.getElementById('room-references-drawer');
    const attachFileRoomBtn = document.getElementById('attach-file-room-btn');
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

    closeRoomBtn?.addEventListener('click', () => roomModal?.classList.remove('active'));
    cancelRoomBtn?.addEventListener('click', () => roomModal?.classList.remove('active'));

    createRoomForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = roomNameInput.value.trim();
      const desc = roomDescInput.value.trim();
      if (!name) return;

      try {
        RAG.utils.showToast('Creating workspace room...', 'info');
        const room = await API.createRoom(name, desc);

        const checked = roomDocCheckboxes?.querySelectorAll('input[name="room_docs"]:checked');
        if (checked && checked.length > 0) {
          await Promise.all(Array.from(checked).map((input) => API.attachDocumentToRoom(room.id, input.value).catch(() => {})));
        }

        RAG.utils.showToast(`Room '${name}' created!`, 'success');
        roomModal?.classList.remove('active');
        createRoomForm.reset();
        await loadRooms();
        selectRoom(room.id, true);
      } catch (err) {
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
    init: initRoomListeners,
  };

  global.loadRooms = loadRooms;
  global.selectRoom = selectRoom;
  global.deleteRoom = deleteRoom;
  global.detachDocFromRoom = detachDocFromRoom;
})(window);
