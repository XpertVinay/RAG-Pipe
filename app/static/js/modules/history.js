/**
 * Conversation History & Session Management Module
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  let cachedConversations = [];

  async function loadConversations() {
    const tabHistoryBadge = document.getElementById('tab-history-badge');
    const historyCount = document.getElementById('history-count');
    const historyList = document.getElementById('history-list');
    const currentUser = API.getCurrentUser();

    if (!currentUser) {
      if (tabHistoryBadge) tabHistoryBadge.textContent = '0';
      if (historyCount) historyCount.textContent = '0 sessions';
      if (historyList) {
        historyList.innerHTML = `
          <div class="history-empty" style="text-align: center; padding: 28px 10px;">
            <span>Sign in to access your chat history.</span>
          </div>
        `;
      }
      cachedConversations = [];
      return;
    }

    try {
      const convs = await API.getConversations(RAG.state.currentRoomId);
      cachedConversations = convs || [];
      if (tabHistoryBadge) tabHistoryBadge.textContent = convs ? convs.length : 0;
      if (historyCount) historyCount.textContent = `${convs ? convs.length : 0} sessions`;

      if (!historyList) return;

      if (!convs || convs.length === 0) {
        historyList.innerHTML = `
          <div class="history-empty">
            <span>No saved conversations for this room.<br>Start chatting to begin.</span>
          </div>
        `;
        return;
      }

      historyList.innerHTML = convs
        .map((c) => {
          const isActive = c.id === RAG.state.currentConversationId;
          const time = new Date(c.updated_at).toLocaleDateString([], {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          });

          return `
            <div class="history-card ${isActive ? 'active' : ''}" onclick="window.selectConversation('${c.id}')">
              <div class="history-card-header">
                <span class="history-title" title="${RAG.utils.escapeHtml(c.title)}">${RAG.utils.escapeHtml(c.title)}</span>
                <button class="history-del-btn" type="button" onclick="event.stopPropagation(); event.preventDefault(); window.deleteConversation('${c.id}', event)" title="Delete session">🗑️</button>
              </div>
              <div class="history-meta">
                <span>${time}</span>
                <span>${c.message_count ? `${c.message_count} messages` : ''}</span>
              </div>
            </div>
          `;
        })
        .join('');
    } catch (e) {
      console.warn('Failed to load conversations:', e);
    }
  }

  async function loadConversationMessages(convId) {
    const messagesContainer = document.getElementById('messages-container');
    try {
      const conv = await API.getConversation(convId);
      RAG.state.currentConversationId = conv.id;
      localStorage.setItem('rag_active_conv_id', conv.id);
      if (messagesContainer) messagesContainer.innerHTML = '';

      if (!conv.messages || conv.messages.length === 0) {
        if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
      } else {
        conv.messages.forEach((msg) => {
          if (msg.role === 'user') {
            if (RAG.chat?.appendMessage) RAG.chat.appendMessage('user', msg.content);
          } else {
            if (RAG.markdown?.renderAssistantMessage) {
              RAG.markdown.renderAssistantMessage({
                content: msg.content,
                citations: msg.citations || [],
                meta: msg.metadata_info || {},
                timestamp: msg.created_at,
              });
            }
          }
        });
        if (RAG.utils?.scheduleScrollToBottom) {
          RAG.utils.scheduleScrollToBottom(true);
        }
      }
    } catch (e) {
      console.warn('Failed to load messages for conversation:', e);
      RAG.state.currentConversationId = null;
      localStorage.removeItem('rag_active_conv_id');
      if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
    }
  }

  function selectConversation(convId) {
    RAG.utils.closeMobileSidebar();
    if (convId === RAG.state.currentConversationId) return;
    loadConversationMessages(convId);
    loadConversations();
  }

  async function deleteConversation(convId, ev) {
    if (ev) {
      ev.stopPropagation();
      ev.preventDefault();
    }
    const c = (cachedConversations || []).find((x) => x.id === convId);
    const title = c ? c.title : 'Chat Session';
    const msgCount = c?.message_count ? `${c.message_count} messages` : 'Conversation Session';

    RAG.utils.showConfirmModal({
      title: 'Delete Chat Session',
      headerIcon: '🗑️',
      itemIcon: '💬',
      itemName: title,
      itemMeta: msgCount,
      prompt: 'Are you sure you want to delete this chat session? All queries, generated answers, citations, and conversation messages will be permanently deleted.',
      confirmText: 'Delete Session',
      onConfirm: async () => {
        try {
          await API.deleteConversation(convId);
          RAG.utils.showToast('Conversation deleted successfully', 'info');
          if (RAG.state.currentConversationId === convId) {
            RAG.state.currentConversationId = null;
            localStorage.removeItem('rag_active_conv_id');
            const messagesContainer = document.getElementById('messages-container');
            if (messagesContainer) messagesContainer.innerHTML = '';
            if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
          }
          await loadConversations();
        } catch (e) {
          RAG.utils.showToast(e.message, 'error');
        }
      },
    });
  }

  async function clearAllData() {
    RAG.utils.showConfirmModal({
      title: 'Delete All Chat & Memory Data',
      headerIcon: '⚠️',
      itemIcon: '🗑️',
      itemName: 'All Conversations & Memories',
      itemMeta: 'Permanent Wipe',
      prompt: 'Are you sure you want to permanently delete ALL conversation threads, messages, and saved conversational memory? Your workspace will be reset to a clean state.',
      confirmText: 'Delete All Data',
      onConfirm: async () => {
        try {
          let res;
          try {
            res = await API.clearAllData(RAG.state.currentRoomId || null);
          } catch (err) {
            // If room-scoped wipe had an authorization or not-found conflict, fallback to global user clear
            res = await API.clearAllData(null);
          }
          RAG.state.currentConversationId = null;
          localStorage.removeItem('rag_active_conv_id');
          const messagesContainer = document.getElementById('messages-container');
          if (messagesContainer) messagesContainer.innerHTML = '';
          if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
          cachedConversations = [];
          await loadConversations();
          if (window.updateMemoryBadgeInitial) window.updateMemoryBadgeInitial();
          if (RAG.memory?.loadMemories) RAG.memory.loadMemories();
          RAG.utils.showToast(res?.message || 'All conversation and memory data deleted', 'success');
        } catch (e) {
          // Even on unexpected network failure, wipe client workspace state cleanly
          RAG.state.currentConversationId = null;
          localStorage.removeItem('rag_active_conv_id');
          const messagesContainer = document.getElementById('messages-container');
          if (messagesContainer) messagesContainer.innerHTML = '';
          if (RAG.chat?.showWelcomeScreen) RAG.chat.showWelcomeScreen();
          cachedConversations = [];
          await loadConversations();
          RAG.utils.showToast(e.message || 'Failed to delete all data', 'error');
        }
      },
    });
  }

  function initHistoryListeners() {
    const clearBtn = document.getElementById('clear-all-data-btn');
    clearBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      clearAllData();
    });

    const settingsClearBtn = document.getElementById('settings-clear-all-data-btn');
    settingsClearBtn?.addEventListener('click', (e) => {
      e.preventDefault();
      const settingsModal = document.getElementById('settings-modal');
      if (settingsModal) settingsModal.classList.remove('active');
      clearAllData();
    });
  }

  RAG.history = {
    loadConversations,
    loadConversationMessages,
    selectConversation,
    deleteConversation,
    clearAllData,
    init: initHistoryListeners,
  };

  // Expose on RAG.chat as well for convenience and backwards-compatibility
  RAG.chat = RAG.chat || {};
  RAG.chat.loadConversationMessages = loadConversationMessages;

  global.loadConversations = loadConversations;
  global.selectConversation = selectConversation;
  global.deleteConversation = deleteConversation;
  global.clearAllData = clearAllData;
})(window);

