/**
 * Consultation Call & Live Transcripts Workspace Module
 * Bridges LLM App Creation Prompts, Projects Table Records, and Communication Channels (Gmeet, Teams, Zoom, etc.)
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  let activeCallTimerInterval = null;
  let callTimerSeconds = 0;
  let currentActiveProjectId = null;
  let rawTranscriptText = '';

  /**
   * Submit an application project request directly from the chat prompt card
   */
  async function submitAppProjectRequest(cardId) {
    const card = document.getElementById(cardId);
    if (!card) return;

    const nameInput = card.querySelector('.app-req-name-input');
    const clientNameInput = card.querySelector('.app-req-client-name-input');
    const emailInput = card.querySelector('.app-req-email-input');
    const phoneInput = card.querySelector('.app-req-phone-input');
    const channelSelect = card.querySelector('.app-req-channel-select');
    const submitBtn = card.querySelector('.app-req-btn-submit');
    const statusArea = card.querySelector('.app-req-status-area');

    const name = nameInput?.value.trim();
    const clientName = clientNameInput?.value.trim();
    const email = emailInput?.value.trim();
    const phone = phoneInput?.value.trim() || '';
    const channel = channelSelect?.value || 'Gmeet';

    if (!name) {
      RAG.utils.showToast('Please enter an Application or Project title', 'warning');
      nameInput?.focus();
      return;
    }
    if (!clientName) {
      RAG.utils.showToast('Please enter your name', 'warning');
      clientNameInput?.focus();
      return;
    }
    if (!email || !email.includes('@')) {
      RAG.utils.showToast('Please provide a valid email address', 'warning');
      emailInput?.focus();
      return;
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<span>⏳ Registering Project...</span>';
    }

    try {
      const payload = {
        name,
        description: `Application development request initiated via LLM chat prompt. Preferred Channel: ${channel}.`,
        client_name: clientName,
        email,
        phone,
        communication_channel: channel,
        room_id: RAG.state.currentRoomId || null,
        conversation_id: RAG.state.currentConversationId || null,
        tags: ['app-request', channel.toLowerCase(), 'prompt-initiated'],
      };

      const project = await API.createAppProjectRequest(payload);
      RAG.utils.showToast(`Application request created on projects table! (ID: ${project.id.slice(0, 8)})`, 'success');

      // Update card UI with verified confirmation and call action
      if (statusArea) {
        statusArea.style.display = 'block';
        statusArea.innerHTML = `
          <div class="app-req-success-banner">
            <div>
              <div style="font-weight: 700; color: #10b981; font-size: 0.85rem; display: flex; align-items: center; gap: 6px;">
                <span>✅</span>
                <span>Project Request Registered on Projects Table</span>
              </div>
              <div style="font-size: 0.74rem; color: #cbd5e1; margin-top: 3px;">
                Project: <strong>${RAG.utils.escapeHtml(project.name)}</strong> | Channel: <strong>${RAG.utils.escapeHtml(project.communication_channel || channel)}</strong> | Contact: <strong>${RAG.utils.escapeHtml(project.client_name)}</strong>
              </div>
            </div>
            <button type="button" class="app-req-btn-call" onclick="window.openInitiateCallModal('${project.id}')">
              <span>📞 Initiate Call (with Transcripts)</span>
              <span style="font-size: 0.8rem;">➔</span>
            </button>
          </div>
        `;
      }

      // Hide submission inputs
      const formGrid = card.querySelector('.app-request-form-grid');
      const actions = card.querySelector('.app-request-actions');
      if (formGrid) formGrid.style.display = 'none';
      if (actions) actions.style.display = 'none';

      // Reload sidebar room projects if in a room
      if (RAG.state.currentRoomId && RAG.rooms?.loadRoomItems) {
        await RAG.rooms.loadRoomItems(RAG.state.currentRoomId, RAG.state.roomFilter || 'all');
      }
    } catch (err) {
      console.error('Failed to submit application project request:', err);
      RAG.utils.showToast(err.message || 'Failed to create application project request', 'error');
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<span>🚀 Submit Project Request &amp; Prepare Call</span>';
      }
    }
  }

  /**
   * Launch the Call Initiation modal accompanied by complete conversation transcripts
   */
  async function openInitiateCallModal(projectId) {
    const modal = document.getElementById('call-initiate-modal');
    if (!modal) {
      RAG.utils.showToast('Call modal container not found', 'error');
      return;
    }

    currentActiveProjectId = projectId;
    modal.classList.add('active');

    // Reset fields to loading state
    const titleEl = document.getElementById('call-modal-project-title');
    const channelBadge = document.getElementById('call-channel-badge');
    const timerEl = document.getElementById('call-live-timer');
    const joinBtn = document.getElementById('call-join-link-btn');
    const linkInput = document.getElementById('call-meeting-link-input');
    const clientNameEl = document.getElementById('call-client-name');
    const clientEmailEl = document.getElementById('call-client-email');
    const clientPhoneEl = document.getElementById('call-client-phone');
    const clientChannelEl = document.getElementById('call-client-channel');
    const notesInput = document.getElementById('call-notes-input');
    const transcriptsArea = document.getElementById('transcripts-content-area');
    const turnCountEl = document.getElementById('transcripts-turn-count');

    if (transcriptsArea) {
      transcriptsArea.innerHTML = `
        <div style="text-align: center; color: var(--text-muted); padding: 40px 20px;">
          <span style="font-size: 1.5rem; display: block; margin-bottom: 8px;">⏳</span>
          Synchronizing project details and compiling conversation transcripts...
        </div>
      `;
    }

    // Start live duration timer
    clearInterval(activeCallTimerInterval);
    callTimerSeconds = 0;
    if (timerEl) timerEl.textContent = '⏱️ 00:00';
    activeCallTimerInterval = setInterval(() => {
      callTimerSeconds++;
      const mins = String(Math.floor(callTimerSeconds / 60)).padStart(2, '0');
      const secs = String(callTimerSeconds % 60).padStart(2, '0');
      if (timerEl) timerEl.textContent = `⏱️ ${mins}:${secs}`;
    }, 1000);

    try {
      // Call backend initiate-call endpoint
      const res = await API.initiateProjectCall(projectId);

      if (titleEl) titleEl.textContent = res.name || 'Application Project';

      // Set channel badge colors
      const channel = res.communication_channel || 'Gmeet';
      if (channelBadge) {
        channelBadge.textContent = channel;
        if (channel.toLowerCase().includes('team')) {
          channelBadge.style.background = 'rgba(168, 85, 247, 0.2)';
          channelBadge.style.color = '#c084fc';
          channelBadge.style.borderColor = 'rgba(168, 85, 247, 0.4)';
        } else if (channel.toLowerCase().includes('zoom')) {
          channelBadge.style.background = 'rgba(59, 130, 246, 0.2)';
          channelBadge.style.color = '#60a5fa';
          channelBadge.style.borderColor = 'rgba(59, 130, 246, 0.4)';
        } else {
          channelBadge.style.background = 'rgba(16, 185, 129, 0.2)';
          channelBadge.style.color = '#34d399';
          channelBadge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
        }
      }

      // Set meeting link
      const meetingUrl = res.meeting_link || 'https://meet.google.com/new';
      if (joinBtn) {
        joinBtn.href = meetingUrl;
        joinBtn.onclick = () => {
          RAG.utils.showToast(`Launching ${channel} consultation in new tab...`, 'info');
        };
      }
      if (linkInput) linkInput.value = meetingUrl;

      // Set client info
      if (clientNameEl) clientNameEl.textContent = res.client_name || '—';
      if (clientEmailEl) {
        clientEmailEl.textContent = res.email || '—';
        clientEmailEl.href = res.email ? `mailto:${res.email}` : '#';
      }
      if (clientPhoneEl) clientPhoneEl.textContent = res.phone || '—';
      if (clientChannelEl) clientChannelEl.textContent = channel;

      // Transcripts display
      rawTranscriptText = res.transcripts || '';
      renderTranscriptsDisplay(rawTranscriptText, transcriptsArea, turnCountEl);

      RAG.utils.showToast(`Call initialized via ${channel} with transcripts attached`, 'success');

      // Refresh sidebar items if applicable
      if (RAG.state.currentRoomId && RAG.rooms?.loadRoomItems) {
        RAG.rooms.loadRoomItems(RAG.state.currentRoomId, RAG.state.roomFilter || 'all');
      }
    } catch (err) {
      console.error('Error initiating call:', err);
      RAG.utils.showToast(err.message || 'Failed to initiate consultation call', 'error');
      if (transcriptsArea) {
        transcriptsArea.innerHTML = `
          <div style="text-align: center; color: #ef4444; padding: 30px 20px;">
            ⚠️ Failed to load call workspace: ${RAG.utils.escapeHtml(err.message || String(err))}
          </div>
        `;
      }
    }
  }

  /**
   * Parse plain text / formatted transcripts into readable turn cards
   */
  function renderTranscriptsDisplay(text, container, countBadge, filterTerm = '') {
    if (!container) return;

    if (!text || !text.trim()) {
      container.innerHTML = `
        <div style="text-align: center; color: var(--text-muted); padding: 40px 20px;">
          (No message transcripts recorded for this conversation thread yet.)
        </div>
      `;
      if (countBadge) countBadge.textContent = '0 Turns';
      return;
    }

    const lines = text.split('\n');
    const turns = [];
    let currentTurn = null;

    for (const rawLine of lines) {
      const line = rawLine.trim();
      const userMatch = line.match(/^\[(👤\s*USER|USER)\s*\|\s*([^\]]+)\]/i);
      const aiMatch = line.match(/^\[(🤖\s*AI ASSISTANT|AI ASSISTANT)\s*\|\s*([^\]]+)\]/i);

      if (userMatch) {
        if (currentTurn) turns.push(currentTurn);
        currentTurn = { role: 'user', time: userMatch[2], lines: [] };
      } else if (aiMatch) {
        if (currentTurn) turns.push(currentTurn);
        currentTurn = { role: 'assistant', time: aiMatch[2], lines: [] };
      } else if (line.startsWith('---') || line.startsWith('===') || line.startsWith('Thread Title:')) {
        // Skip metadata header delimiters
      } else if (currentTurn) {
        if (line) currentTurn.lines.push(line);
      }
    }
    if (currentTurn) turns.push(currentTurn);

    if (countBadge) {
      countBadge.textContent = `${turns.length} Turn${turns.length === 1 ? '' : 's'}`;
    }

    // Filter turns if search term is active
    let displayTurns = turns;
    if (filterTerm && filterTerm.trim()) {
      const term = filterTerm.trim().toLowerCase();
      displayTurns = turns.filter((t) => t.lines.join(' ').toLowerCase().includes(term));
    }

    if (displayTurns.length === 0) {
      if (turns.length > 0) {
        container.innerHTML = `
          <div style="text-align: center; color: var(--text-muted); padding: 30px 10px;">
            No transcript turns match "<strong>${RAG.utils.escapeHtml(filterTerm)}</strong>".
          </div>
        `;
      } else {
        // Fallback: render raw text with line breaks
        container.innerHTML = `
          <pre style="white-space: pre-wrap; font-family: monospace; font-size: 0.78rem; color: var(--text-secondary); line-height: 1.5;">${RAG.utils.escapeHtml(text)}</pre>
        `;
      }
      return;
    }

    container.innerHTML = displayTurns
      .map((turn, idx) => {
        const isUser = turn.role === 'user';
        const roleLabel = isUser ? '👤 Requester / Client' : '🤖 AI Solution Architect';
        const badgeColor = isUser ? '#818cf8' : '#34d399';
        const cardClass = isUser ? 'transcript-message-turn user-turn' : 'transcript-message-turn assistant-turn';
        const turnBody = turn.lines.join('\n');

        return `
          <div class="${cardClass}">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; font-size: 0.72rem;">
              <strong style="color: ${badgeColor}; display: flex; align-items: center; gap: 5px;">
                ${roleLabel}
              </strong>
              <span style="color: var(--text-muted); font-size: 0.68rem; font-family: monospace;">
                ${turn.time || ''}
              </span>
            </div>
            <div style="font-size: 0.8rem; line-height: 1.5; color: var(--text-primary); white-space: pre-wrap;">${RAG.utils.escapeHtml(turnBody)}</div>
          </div>
        `;
      })
      .join('');
  }

  /**
   * Initialize modal listeners
   */
  function initCallWorkspaceListeners() {
    const modal = document.getElementById('call-initiate-modal');
    const closeBtn = document.getElementById('close-call-modal-btn');
    const dismissBtn = document.getElementById('dismiss-call-modal-btn');
    const copyLinkBtn = document.getElementById('copy-meeting-link-btn');
    const copyTranscriptsBtn = document.getElementById('copy-transcripts-btn');
    const exportTranscriptsBtn = document.getElementById('export-transcripts-btn');
    const searchInput = document.getElementById('transcript-search-input');
    const saveNotesBtn = document.getElementById('save-call-notes-btn');
    const notesInput = document.getElementById('call-notes-input');

    const closeModal = () => {
      modal?.classList.remove('active');
      clearInterval(activeCallTimerInterval);
    };

    closeBtn?.addEventListener('click', closeModal);
    dismissBtn?.addEventListener('click', closeModal);

    // Copy meeting link
    copyLinkBtn?.addEventListener('click', () => {
      const link = document.getElementById('call-meeting-link-input')?.value;
      if (link) {
        navigator.clipboard.writeText(link).then(() => {
          RAG.utils.showToast('Meeting link copied to clipboard!', 'success');
        });
      }
    });

    // Copy transcripts
    copyTranscriptsBtn?.addEventListener('click', () => {
      if (rawTranscriptText) {
        navigator.clipboard.writeText(rawTranscriptText).then(() => {
          RAG.utils.showToast('Full conversation transcripts copied!', 'success');
        });
      }
    });

    // Export transcripts to .txt file
    exportTranscriptsBtn?.addEventListener('click', () => {
      if (!rawTranscriptText) {
        RAG.utils.showToast('No transcript text available to export', 'warning');
        return;
      }
      const title = document.getElementById('call-modal-project-title')?.textContent || 'project';
      const cleanTitle = title.toLowerCase().replace(/[^a-z0-9_-]/g, '_');
      const blob = new Blob([rawTranscriptText], { type: 'text/plain;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `transcript_${cleanTitle}.txt`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      RAG.utils.showToast('Transcript exported as .txt file', 'success');
    });

    // Live search in transcripts
    searchInput?.addEventListener('input', (e) => {
      const term = e.target.value;
      const container = document.getElementById('transcripts-content-area');
      const countBadge = document.getElementById('transcripts-turn-count');
      renderTranscriptsDisplay(rawTranscriptText, container, countBadge, term);
    });

    // Save call notes
    saveNotesBtn?.addEventListener('click', async () => {
      if (!currentActiveProjectId) return;
      const notes = notesInput?.value.trim();
      try {
        saveNotesBtn.disabled = true;
        saveNotesBtn.textContent = 'Saving...';
        await API.initiateProjectCall(currentActiveProjectId, { call_notes: notes });
        RAG.utils.showToast('Consultation notes saved to project record', 'success');
      } catch (err) {
        RAG.utils.showToast(err.message || 'Failed to save notes', 'error');
      } finally {
        saveNotesBtn.disabled = false;
        saveNotesBtn.textContent = '💾 Save Notes';
      }
    });
  }

  // Register on RAG
  RAG.calls = {
    submitAppProjectRequest,
    openInitiateCallModal,
    initCallWorkspaceListeners,
  };

  // Expose globally
  global.submitAppProjectRequest = submitAppProjectRequest;
  global.openInitiateCallModal = openInitiateCallModal;

  // Initialize once DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initCallWorkspaceListeners);
  } else {
    initCallWorkspaceListeners();
  }
})(window);
