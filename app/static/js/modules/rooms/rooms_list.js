/**
 * Rooms List Rendering, Workspace Selection & Reference Cards
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.rooms = RAG.rooms || {};

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

      renderRoomsList();

      if (RAG.state.rooms.length === 0) {
        RAG.state.currentRoomId = null;
        RAG.state.currentRoom = null;
        API.setActiveRoomId(null);
        const bannerRoomName = document.getElementById('banner-room-name');
        const convTitle = document.getElementById('conv-title');
        const convSubtitle = document.getElementById('conv-subtitle');
        if (bannerRoomName) bannerRoomName.textContent = 'No Workspace';
        if (convTitle) convTitle.textContent = 'RAG AI Assistant';
        if (convSubtitle) convSubtitle.textContent = 'Create a workspace room or start chatting to begin';
        if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
        return;
      }

      // Check URL query parameter ?room=... or API.getActiveRoomId()
      const urlParams = new URLSearchParams(window.location.search);
      const targetRoomId = urlParams.get('room') || API.getActiveRoomId();
      const matchedRoom = RAG.state.rooms.find((r) => r.id === targetRoomId);

      if (matchedRoom) {
        selectRoom(matchedRoom.id, false);
      } else if (RAG.state.rooms.length > 0) {
        selectRoom(RAG.state.rooms[0].id, false);
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

      // Resolve conversation to load: URL ?conv=..., localStorage, or room.active_conversation_id
      const urlParams = new URLSearchParams(window.location.search);
      const urlConvId = urlParams.get('conv');
      const storedConvId = localStorage.getItem('rag_active_conv_id');
      const convToLoad = urlConvId || room.active_conversation_id || storedConvId;

      if (convToLoad) {
        RAG.state.currentConversationId = convToLoad;
        localStorage.setItem('rag_active_conv_id', convToLoad);
        if (RAG.history?.loadConversationMessages) {
          await RAG.history.loadConversationMessages(convToLoad);
        } else if (RAG.chat?.loadConversationMessages) {
          await RAG.chat.loadConversationMessages(convToLoad);
        }
      } else {
        RAG.state.currentConversationId = null;
        localStorage.removeItem('rag_active_conv_id');
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

  RAG.rooms.loadRooms = loadRooms;
  RAG.rooms.renderRoomsList = renderRoomsList;
  RAG.rooms.selectRoom = selectRoom;
  RAG.rooms.renderRoomReferences = renderRoomReferences;
})(window);
