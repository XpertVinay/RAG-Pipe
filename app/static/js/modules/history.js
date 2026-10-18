/**
 * Conversation History & Session Management Module
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

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
      return;
    }

    try {
      const convs = await API.getConversations(RAG.state.currentRoomId);
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
                <button class="history-del-btn" onclick="window.deleteConversation('${c.id}', event)" title="Delete session">🗑️</button>
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
      }
    } catch (e) {
      console.warn('Failed to load messages for conversation:', e);
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
    if (ev) ev.stopPropagation();
    if (!confirm('Are you sure you want to delete this chat session?')) return;
    try {
      await API.deleteConversation(convId);
      RAG.utils.showToast('Conversation deleted', 'info');
      if (RAG.state.currentConversationId === convId) {
        if (RAG.chat?.startNewChat) RAG.chat.startNewChat();
      } else {
        loadConversations();
      }
    } catch (e) {
      RAG.utils.showToast(e.message, 'error');
    }
  }

  RAG.history = {
    loadConversations,
    loadConversationMessages,
    selectConversation,
    deleteConversation,
  };

  global.loadConversations = loadConversations;
  global.selectConversation = selectConversation;
  global.deleteConversation = deleteConversation;
})(window);
