/**
 * Interactive RAG Chat, Streaming SSE Controller, Prompts & Copy Actions Module
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  let sseClient = null;

  function appendMessage(role, content) {
    const messagesContainer = document.getElementById('messages-container');
    if (!messagesContainer) return;
    const row = document.createElement('div');
    row.className = `message-row ${role}`;
    row.innerHTML = `
      <div class="message-avatar">${role === 'user' ? '👤' : '⚡'}</div>
      <div class="message-content-wrapper">
        <div class="message-bubble">${RAG.utils.escapeHtml(content)}</div>
      </div>
    `;
    messagesContainer.appendChild(row);
    RAG.utils.scheduleScrollToBottom(true);
  }

  function showWelcomeScreen() {
    const messagesContainer = document.getElementById('messages-container');
    if (!messagesContainer) return;
    const currentUser = API.getCurrentUser();

    if (!currentUser) {
      messagesContainer.innerHTML = `
        <div class="welcome-screen">
          <h3>RAG Agent — Grounded AI Assistant</h3>
          <p>Sign in or register to create workspaces, upload documents, and ask grounded questions with verifiable citations.</p>
          <div style="margin-top: 18px; display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
            <button class="btn btn-primary" onclick="window.showAuthModal ? window.showAuthModal('signin') : (window.switchAuthTab?.('signin'), document.getElementById('auth-modal')?.classList.add('active'))">
              Sign In / Register
            </button>
            <button class="btn btn-outline" id="welcome-demo-login-btn" onclick="document.getElementById('demo-login-btn')?.click()">
              ⚡ Demo Account
            </button>
          </div>
        </div>
      `;
      return;
    }

    const fileCount = RAG.state.currentRoom?.documents?.length || 0;
    const roomTitle = RAG.state.currentRoom?.name || 'Workspace';

    messagesContainer.innerHTML = `
      <div class="welcome-screen">
        <h3>${RAG.utils.escapeHtml(roomTitle)} — Grounded AI Assistant</h3>
        <p>${
          fileCount > 0
            ? `Ready to answer questions grounded in <strong>${fileCount} indexed file(s)</strong> in this room. Context persists across browser refreshes.`
            : `Upload or attach documents to this workspace room to begin grounded Q&A with verifiable citations.`
        }</p>
        <div class="quick-prompts">
          <button class="quick-prompt-btn" onclick="window.usePrompt('Summarize the key concepts and points from the uploaded documents in this room.')">
            ✨ "Summarize the key concepts and points from the uploaded documents."
          </button>
          <button class="quick-prompt-btn" onclick="window.usePrompt('What are the main topics and important references covered in these files?')">
            🔍 "What are the main topics and important references covered in these files?"
          </button>
        </div>
      </div>
    `;
  }

  async function startNewChat() {
    RAG.utils.closeMobileSidebar();
    const currentUser = API.getCurrentUser();
    if (!currentUser) {
      if (RAG.auth?.showAuthModal) {
        RAG.auth.showAuthModal('signin', 'Authentication required. Please sign in or register to start a new chat.');
      } else {
        const authModal = document.getElementById('auth-modal');
        if (authModal) authModal.classList.add('active');
      }
      return;
    }

    const messagesContainer = document.getElementById('messages-container');
    try {
      const title = RAG.state.currentRoom ? `${RAG.state.currentRoom.name} Chat` : 'New Chat';
      const conv = await API.createConversation(title, RAG.state.currentRoomId);
      RAG.state.currentConversationId = conv.id;
      localStorage.setItem('rag_active_conv_id', conv.id);
      if (messagesContainer) messagesContainer.innerHTML = '';
      showWelcomeScreen();
      RAG.utils.showToast('Started new conversation thread', 'info');
      if (RAG.history?.loadConversations) RAG.history.loadConversations();
    } catch (e) {
      console.error('Failed to create conversation:', e);
      if (e.message && (e.message.includes('401') || e.message.includes('Authentication required'))) {
        if (RAG.auth?.showAuthModal) {
          RAG.auth.showAuthModal('signin', 'Authentication required to start a new chat.');
        }
      }
    }
  }

  async function submitQuery() {
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const messagesContainer = document.getElementById('messages-container');
    const charCounter = document.getElementById('chat-char-counter');

    if (!chatInput) return;
    const rawValue = chatInput.value;
    const text = rawValue.trim();

    // JavaScript Input Validation
    if (RAG.validator) {
      const err = RAG.validator.validateChatMessage(rawValue);
      if (err) {
        chatInput.classList.remove('input-shake');
        void chatInput.offsetWidth;
        chatInput.classList.add('is-invalid', 'input-shake');
        setTimeout(() => chatInput.classList.remove('input-shake'), 400);
        RAG.utils.showToast(err, 'warning');
        chatInput.focus();
        return;
      } else {
        chatInput.classList.remove('is-invalid');
      }
    } else if (!text) {
      return;
    }

    const currentUser = API.getCurrentUser();
    if (!currentUser) {
      if (RAG.auth?.showAuthModal) {
        RAG.auth.showAuthModal('signin', 'Authentication required. Please sign in or register to chat.');
      } else {
        const authModal = document.getElementById('auth-modal');
        if (authModal) authModal.classList.add('active');
        RAG.utils.showToast('Authentication required. Please sign in or register to chat.', 'warning');
      }
      return;
    }

    RAG.state.lastUserQuery = text;

    const welcome = messagesContainer?.querySelector('.welcome-screen');
    if (welcome) welcome.remove();

    appendMessage('user', text);
    chatInput.value = '';
    chatInput.style.height = 'auto';
    chatInput.classList.remove('is-invalid');
    if (charCounter) charCounter.style.display = 'none';
    if (sendBtn) sendBtn.disabled = true;

    const assistantRow = document.createElement('div');
    assistantRow.className = 'message-row assistant';
    assistantRow.innerHTML = `
      <div class="message-avatar">⚡</div>
      <div class="message-content-wrapper">
        <div class="streaming-status">
          <span class="status-pulse"></span>
          <span class="status-text">Analyzing query and scoping room references...</span>
        </div>
        <div class="message-bubble">
          <span class="bubble-text"></span><span class="streaming-cursor"></span>
        </div>
      </div>
    `;
    messagesContainer.appendChild(assistantRow);
    RAG.utils.scheduleScrollToBottom(true);

    const avatarEl = assistantRow.querySelector('.message-avatar');
    const statusEl = assistantRow.querySelector('.status-text');
    const bubbleText = assistantRow.querySelector('.bubble-text');

    let accumulatedContent = '';
    let currentCitations = [];
    let receivedMeta = {};

    const roomDocIds = RAG.state.currentRoom?.documents?.map((d) => d.id) || null;

    if (!sseClient) sseClient = new SSEClient();

    await sseClient.streamQuery({
      message: text,
      conversationId: RAG.state.currentConversationId,
      roomId: RAG.state.currentRoomId,
      documentIds: roomDocIds,
      provider: RAG.state.activeSettings?.default_chat_provider,
      model: RAG.state.activeSettings?.default_chat_model,
      topK: RAG.state.activeSettings?.retrieval_top_k || 4,
      onStatus: (msg) => {
        if (statusEl) statusEl.textContent = msg;
      },
      onMeta: (meta) => {
        receivedMeta = meta;
        if (meta.response_type === 'grounded') {
          avatarEl.textContent = '🛡️';
          avatarEl.className = 'message-avatar grounded';
        } else if (meta.response_type === 'insufficient_info') {
          avatarEl.textContent = '⚠️';
          avatarEl.className = 'message-avatar insufficient_info';
        } else if (meta.response_type === 'greeting') {
          avatarEl.textContent = '✨';
          avatarEl.className = 'message-avatar greeting';
        }
      },
      onToken: (tok) => {
        accumulatedContent += tok;
        bubbleText.textContent = accumulatedContent;
        RAG.utils.scheduleScrollToBottom();
      },
      onCitations: (citations) => {
        currentCitations = citations || [];
      },
      onDone: (data) => {
        if (sendBtn) sendBtn.disabled = false;
        chatInput.focus();

        const finalCitations = (data && data.citations) || currentCitations;
        const finalMeta = Object.assign({}, receivedMeta, data || {});

        assistantRow.remove();
        if (RAG.markdown?.renderAssistantMessage) {
          RAG.markdown.renderAssistantMessage({
            content: accumulatedContent || data?.answer || '',
            citations: finalCitations,
            meta: finalMeta,
            timestamp: new Date().toISOString(),
          });
        }

        if (RAG.history?.loadConversations) RAG.history.loadConversations();
      },
      onError: (err) => {
        if (sendBtn) sendBtn.disabled = false;
        assistantRow.remove();

        const errMsg = typeof err === 'string' ? err : (err?.message || '');
        const isAuthErr = err?.status === 401 ||
          err?.isAuthRequired ||
          errMsg.includes('401') ||
          errMsg.toLowerCase().includes('authentication required') ||
          errMsg.toLowerCase().includes('not authenticated');

        if (isAuthErr) {
          if (RAG.auth?.showAuthModal) {
            RAG.auth.showAuthModal('signin', 'Authentication required to access this conversation. Please sign in or register.');
          } else {
            const authModal = document.getElementById('auth-modal');
            if (authModal) authModal.classList.add('active');
            RAG.utils.showToast('Authentication required to access this conversation. Please sign in or register.', 'warning');
          }
          return;
        }

        if (RAG.markdown?.renderAssistantMessage) {
          RAG.markdown.renderAssistantMessage({
            content: `An error occurred: ${errMsg || err}`,
            citations: [],
            meta: { response_type: 'error' },
            timestamp: new Date().toISOString(),
          });
        }
      },
    });
  }

  function copyCode(btn, codeId) {
    const container = document.getElementById(codeId);
    if (!container) return;
    const codeEl = container.querySelector('pre code');
    if (!codeEl) return;
    const codeText = codeEl.innerText || codeEl.textContent;

    navigator.clipboard.writeText(codeText).then(() => {
      const label = btn.querySelector('.copy-label');
      const icon = btn.querySelector('.copy-icon');
      if (label) label.textContent = 'Copied!';
      if (icon) icon.textContent = '✓';
      btn.classList.add('copied');
      setTimeout(() => {
        if (label) label.textContent = 'Copy';
        if (icon) icon.textContent = '📋';
        btn.classList.remove('copied');
      }, 2000);
    });
  }

  function copyAnswer(btn) {
    const wrapper = btn.closest('.message-content-wrapper');
    if (!wrapper) return;
    const markdownEl = wrapper.querySelector('.bubble-markdown');
    if (!markdownEl) return;
    const textToCopy = markdownEl.innerText || markdownEl.textContent;

    navigator.clipboard.writeText(textToCopy).then(() => {
      const origHtml = btn.innerHTML;
      btn.innerHTML = '<span>✓</span> Copied!';
      btn.classList.add('copied');
      RAG.utils.showToast('Answer copied to clipboard', 'success');
      setTimeout(() => {
        btn.innerHTML = origHtml;
        btn.classList.remove('copied');
      }, 2000);
    });
  }

  function usePrompt(text) {
    const chatInput = document.getElementById('chat-input');
    if (chatInput) {
      chatInput.value = text;
      chatInput.focus();
      submitQuery();
    }
  }

  function retryLastQuery() {
    const chatInput = document.getElementById('chat-input');
    if (RAG.state.lastUserQuery && chatInput) {
      chatInput.value = RAG.state.lastUserQuery;
      submitQuery();
    }
  }

  function initChatListeners() {
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const newChatBtn = document.getElementById('new-chat-btn');

    newChatBtn?.addEventListener('click', startNewChat);

    chatForm?.addEventListener('submit', (e) => {
      e.preventDefault();
      submitQuery();
    });

    chatInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitQuery();
      }
    });

    chatInput?.addEventListener('input', () => {
      chatInput.style.height = 'auto';
      chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';

      const charCounter = document.getElementById('chat-char-counter');
      const sendBtn = document.getElementById('send-btn');
      const len = chatInput.value.length;

      if (charCounter) {
        if (len > 2500) {
          charCounter.style.display = 'inline-block';
          charCounter.textContent = `${len.toLocaleString()} / 4,000`;
          charCounter.className = 'chat-char-counter' + (len > 4000 ? ' danger' : len > 3500 ? ' warning' : '');
        } else {
          charCounter.style.display = 'none';
        }
      }

      if (len > 4000) {
        chatInput.classList.add('is-invalid');
        if (sendBtn) sendBtn.disabled = true;
      } else {
        chatInput.classList.remove('is-invalid');
        if (sendBtn) sendBtn.disabled = false;
      }
    });
  }

  RAG.chat = {
    appendMessage,
    showWelcomeScreen,
    startNewChat,
    submitQuery,
    copyCode,
    copyAnswer,
    usePrompt,
    retryLastQuery,
    init: initChatListeners,
  };

  global.appendMessage = appendMessage;
  global.showWelcomeScreen = showWelcomeScreen;
  global.startNewChat = startNewChat;
  global.submitQuery = submitQuery;
  global.copyCode = copyCode;
  global.copyAnswer = copyAnswer;
  global.usePrompt = usePrompt;
  global.retryLastQuery = retryLastQuery;
})(window);
