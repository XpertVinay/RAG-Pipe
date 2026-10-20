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
        if (convTitle) convTitle.textContent = 'Chat with Docs';
        if (convSubtitle) convSubtitle.textContent = '';
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

      // Load Room Items (Projects & Chats) for the active room
      await loadRoomItems(roomId, RAG.state.roomFilter || 'all');

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

  async function loadRoomItems(roomId, filterType = 'all') {
    if (!roomId) return;
    try {
      const data = await API.getRoomItems(roomId, filterType);
      RAG.state.roomItems = data.items || [];
      renderRoomItemsList(data);
    } catch (err) {
      console.warn('Failed to load room items:', err);
    }
  }

  function renderRoomItemsList(data) {
    const activeRoomCard = document.querySelector(`.room-card.active`);
    if (!activeRoomCard) return;

    // Check if an items container already exists inside active card
    let itemsContainer = activeRoomCard.querySelector('.room-card-items-panel');
    if (!itemsContainer) {
      itemsContainer = document.createElement('div');
      itemsContainer.className = 'room-card-items-panel';
      itemsContainer.style.cssText = 'margin-top: 10px; padding-top: 8px; border-top: 1px dashed rgba(255,255,255,0.08);';
      activeRoomCard.appendChild(itemsContainer);
    }

    const items = data.items || [];
    const filter = data.filter_type || 'all';

    if (items.length === 0) {
      itemsContainer.innerHTML = `
        <div style="font-size: 0.72rem; color: var(--text-muted); text-align: center; padding: 6px 0;">
          No ${filter === 'all' ? 'projects or chats' : filter} in this room yet.
        </div>
      `;
      return;
    }

    itemsContainer.innerHTML = `
      <div style="font-size: 0.7rem; font-weight: 600; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center;">
        <span>📁 ${filter.toUpperCase()} (${items.length})</span>
        <span style="font-size: 0.65rem; color: var(--text-muted);">Click to open</span>
      </div>
      <div style="display: flex; flex-direction: column; gap: 4px; max-height: 180px; overflow-y: auto;">
        ${items
          .map((item) => {
            const isProject = item.item_type === 'project';
            const isAppRequest = isProject && (item.request_type === 'app_creation' || item.communication_channel);
            const icon = isAppRequest ? '📱' : (isProject ? '📁' : '💬');
            const badgeColor = isAppRequest ? '#34d399' : (isProject ? '#818cf8' : '#34d399');
            const badgeBg = isAppRequest ? 'rgba(16, 185, 129, 0.18)' : (isProject ? 'rgba(99, 102, 241, 0.15)' : 'rgba(16, 185, 129, 0.15)');
            const metaInfo = isAppRequest
              ? (item.communication_channel ? `📞 ${item.communication_channel}` : 'App Request')
              : (isProject ? `Status: ${item.status || 'active'}` : `${item.message_count || 0} msgs`);

            return `
              <div class="room-sub-item-pill" style="display: flex; align-items: center; justify-content: space-between; background: var(--bg-primary); border: 1px solid var(--border-color); border-radius: 4px; padding: 5px 8px; cursor: pointer; transition: all 0.15s ease;"
                onclick="event.stopPropagation(); window.selectRoomSubItem('${item.item_type}', '${item.id}', '${RAG.utils.escapeHtml(item.title).replace(/'/g, "\\'")}')"
                onmouseover="this.style.borderColor='var(--accent-primary)'" onmouseout="this.style.borderColor='var(--border-color)'">
                <div style="display: flex; align-items: center; gap: 6px; overflow: hidden;">
                  <span>${icon}</span>
                  <span style="font-size: 0.75rem; font-weight: 500; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 125px;" title="${RAG.utils.escapeHtml(item.title)}">
                    ${RAG.utils.escapeHtml(item.title)}
                  </span>
                </div>
                <div style="display: flex; align-items: center; gap: 4px;">
                  <span style="font-size: 0.62rem; background: ${badgeBg}; color: ${badgeColor}; padding: 1px 5px; border-radius: 3px;">
                    ${metaInfo}
                  </span>
                  ${
                    isProject
                      ? `
                        <button type="button" class="doc-btn" style="padding: 1px 5px; font-size: 0.62rem; background: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 3px; cursor: pointer;" onclick="event.stopPropagation(); window.openInitiateCallModal('${item.id}')" title="Initiate Call with Transcripts">📞</button>
                        <button type="button" class="doc-btn delete" style="padding: 1px 4px; font-size: 0.65rem;" onclick="event.stopPropagation(); window.deleteProject('${RAG.state.currentRoomId}', '${item.id}')" title="Delete Project">✕</button>
                      `
                      : ''
                  }
                </div>
              </div>
            `;
          })
          .join('')}
      </div>
    `;
  }

  function selectRoomSubItem(itemType, id, title) {
    if (itemType === 'project') {
      RAG.state.activeProjectId = id;
      const pill = document.getElementById('room-active-project-pill');
      const label = document.getElementById('active-project-name');
      if (pill && label) {
        pill.style.display = 'inline-flex';
        label.textContent = title;
      }
      RAG.utils.showToast(`Scoped to project: "${title}"`, 'info');
      // If we have history or chats, we can filter conversations by project
      if (RAG.history?.loadConversations) RAG.history.loadConversations();
    } else if (itemType === 'chat') {
      RAG.state.currentConversationId = id;
      localStorage.setItem('rag_active_conv_id', id);
      const url = new URL(window.location);
      url.searchParams.set('conv', id);
      window.history.replaceState({}, '', url);
      if (RAG.history?.loadConversationMessages) {
        RAG.history.loadConversationMessages(id);
      } else if (RAG.chat?.loadConversationMessages) {
        RAG.chat.loadConversationMessages(id);
      }
    }
  }

  function clearActiveProjectScope() {
    RAG.state.activeProjectId = null;
    const pill = document.getElementById('room-active-project-pill');
    if (pill) pill.style.display = 'none';
    RAG.utils.showToast('Cleared project scope', 'info');
    if (RAG.history?.loadConversations) RAG.history.loadConversations();
  }

  async function openCompactMemoryModal() {
    const modal = document.getElementById('compact-memory-modal');
    if (!modal) return;
    modal.classList.add('active');

    const evalRawTokens = document.getElementById('eval-raw-tokens');
    const evalCompactTokens = document.getElementById('eval-compact-tokens');
    const evalTokensSaved = document.getElementById('eval-tokens-saved');
    const evalReadinessScore = document.getElementById('eval-readiness-score');
    const evalSynthesis = document.getElementById('eval-compact-synthesis');
    const evalStmCount = document.getElementById('eval-stm-count');
    const evalLtmCount = document.getElementById('eval-ltm-count');
    const evalStmList = document.getElementById('eval-stm-list');
    const evalLtmList = document.getElementById('eval-ltm-list');

    try {
      const data = await API.getCompactMemoryEval(RAG.state.currentRoomId, RAG.state.activeProjectId);

      if (evalRawTokens) evalRawTokens.textContent = `${data.raw_estimated_tokens || 0} tok`;
      if (evalCompactTokens) evalCompactTokens.textContent = `${data.compact_tokens || 0} tok`;
      if (evalTokensSaved) evalTokensSaved.textContent = `${data.tokens_saved_percent || 0}%`;
      if (evalReadinessScore) evalReadinessScore.textContent = `${Math.round((data.readiness_score || 0.5) * 100)}%`;
      if (evalSynthesis) evalSynthesis.textContent = data.compact_synthesis || 'Standard verified context.';

      if (evalStmCount) evalStmCount.textContent = `${data.short_term_count || 0} items`;
      if (evalLtmCount) evalLtmCount.textContent = `${data.long_term_count || 0} items`;

      if (evalStmList) {
        if (!data.short_term_items || data.short_term_items.length === 0) {
          evalStmList.innerHTML = `<div style="font-size: 0.74rem; color: var(--text-muted); padding: 4px;">No short-term inquiries recorded yet.</div>`;
        } else {
          evalStmList.innerHTML = data.short_term_items
            .map(
              (i) => `
              <div style="background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 4px; padding: 6px 10px; font-size: 0.74rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                  <strong style="color: #818cf8;">${RAG.utils.escapeHtml(i.meaning_intent)}</strong>
                  <span style="font-size: 0.65rem; color: var(--text-muted);">${i.age_hours}h ago</span>
                </div>
                <div style="color: var(--text-secondary);">${RAG.utils.escapeHtml(i.compact_content)}</div>
              </div>
            `
            )
            .join('');
        }
      }

      if (evalLtmList) {
        if (!data.long_term_items || data.long_term_items.length === 0) {
          evalLtmList.innerHTML = `<div style="font-size: 0.74rem; color: var(--text-muted); padding: 4px;">No enduring constraints or preferences stored yet.</div>`;
        } else {
          evalLtmList.innerHTML = data.long_term_items
            .map(
              (i) => `
              <div style="background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: 4px; padding: 6px 10px; font-size: 0.74rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 2px;">
                  <strong style="color: #34d399;">${RAG.utils.escapeHtml(i.meaning_intent)}</strong>
                  <span style="font-size: 0.65rem; color: var(--text-muted);">${i.age_hours}h ago</span>
                </div>
                <div style="color: var(--text-secondary);">${RAG.utils.escapeHtml(i.compact_content)}</div>
              </div>
            `
            )
            .join('');
        }
      }
    } catch (err) {
      RAG.utils.showToast(err.message || 'Failed to evaluate compact memory', 'error');
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
  RAG.rooms.loadRoomItems = loadRoomItems;
  RAG.rooms.selectRoomSubItem = selectRoomSubItem;
  RAG.rooms.clearActiveProjectScope = clearActiveProjectScope;
  RAG.rooms.openCompactMemoryModal = openCompactMemoryModal;
  RAG.rooms.renderRoomReferences = renderRoomReferences;
  window.selectRoomSubItem = selectRoomSubItem;
  window.clearActiveProjectScope = clearActiveProjectScope;
  window.openCompactMemoryModal = openCompactMemoryModal;
})(window);
