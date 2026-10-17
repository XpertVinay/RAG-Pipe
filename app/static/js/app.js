/**
 * Production RAG Agent UI Controller
 */
document.addEventListener('DOMContentLoaded', () => {
  const sseClient = new SSEClient();

  // State
  let currentConversationId = null;
  let activeDocuments = [];
  let pollInterval = null;
  let activeSettings = null;

  // DOM Elements
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');
  const docsList = document.getElementById('docs-list');
  const docsCount = document.getElementById('docs-count');
  const messagesContainer = document.getElementById('messages-container');
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');
  const sendBtn = document.getElementById('send-btn');
  const newChatBtn = document.getElementById('new-chat-btn');
  const convTitle = document.getElementById('conv-title');
  const providerBadge = document.getElementById('provider-badge');
  const openSettingsBtn = document.getElementById('open-settings-btn');
  const settingsModal = document.getElementById('settings-modal');
  const closeSettingsBtn = document.getElementById('close-settings-btn');
  const saveSettingsBtn = document.getElementById('save-settings-btn');
  const providerSelect = document.getElementById('provider-select');
  const modelInput = document.getElementById('model-input');
  const topkSlider = document.getElementById('topk-slider');
  const topkVal = document.getElementById('topk-val');
  const toastContainer = document.getElementById('toast-container');
  const citationModal = document.getElementById('citation-modal');
  const closeCitationBtn = document.getElementById('close-citation-btn');
  const citationModalBody = document.getElementById('citation-modal-body');

  // File type icons
  const iconMap = {
    pdf: '📄',
    docx: '📝',
    txt: '📃',
    md: '📑',
    csv: '📊',
    html: '🌐',
  };

  // Toast Notification
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span>${type === 'error' ? '⚠️' : '✓'}</span><span>${message}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 250);
    }, 4000);
  }

  // Load System Settings
  async function loadSettings() {
    try {
      const data = await API.getSettings();
      activeSettings = data;
      providerBadge.textContent = `${data.default_chat_provider.toUpperCase()} / ${data.default_chat_model}`;

      if (providerSelect) {
        providerSelect.innerHTML = '';
        data.available_chat_providers.forEach((p) => {
          const opt = document.createElement('option');
          opt.value = p.name;
          opt.textContent = `${p.name.toUpperCase()} ${p.available ? '(Ready)' : '(Not Configured)'}`;
          if (p.name === data.default_chat_provider) opt.selected = true;
          providerSelect.appendChild(opt);
        });
      }

      if (modelInput) modelInput.value = data.default_chat_model;
      if (topkSlider) {
        topkSlider.value = data.retrieval_top_k;
        topkVal.textContent = data.retrieval_top_k;
      }
    } catch (e) {
      console.warn('Could not load settings:', e);
    }
  }

  // Load Document Library
  async function loadDocuments() {
    try {
      const data = await API.getDocuments();
      activeDocuments = data.items || [];
      docsCount.textContent = `${activeDocuments.length} files`;

      if (activeDocuments.length === 0) {
        docsList.innerHTML = `
          <div style="text-align: center; padding: 24px 10px; color: var(--text-muted); font-size: 0.8rem;">
            No documents indexed yet.<br>Drag and drop files above to start.
          </div>
        `;
        return;
      }

      docsList.innerHTML = activeDocuments
        .map((doc) => {
          const icon = iconMap[doc.file_type] || '📄';
          const sizeKb = Math.round(doc.file_size / 1024);
          const date = new Date(doc.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          const isProcessing = doc.status === 'processing' || doc.status === 'queued';

          return `
            <div class="doc-card" id="doc-${doc.id}">
              <div class="doc-card-top">
                <div class="doc-info" title="${doc.filename}">
                  <span class="doc-icon">${icon}</span>
                  <span class="doc-name">${doc.filename}</span>
                </div>
                <div class="doc-actions">
                  <button class="doc-btn" onclick="window.reprocessDoc('${doc.id}')" title="Reprocess Document">🔄</button>
                  <button class="doc-btn delete" onclick="window.deleteDoc('${doc.id}')" title="Delete Document">🗑️</button>
                </div>
              </div>
              <div class="doc-meta">
                <span>${sizeKb} KB • ${doc.chunk_count} chunks</span>
                <span class="status-badge ${doc.status}">
                  ${isProcessing ? '<span class="status-pulse"></span>' : ''}
                  ${doc.status}
                </span>
              </div>
              ${doc.error_message ? `<div style="margin-top: 6px; font-size: 0.7rem; color: var(--status-failed); line-height: 1.3;">${doc.error_message}</div>` : ''}
            </div>
          `;
        })
        .join('');

      // If any document is processing or queued, poll periodically
      const hasPending = activeDocuments.some((d) => d.status === 'processing' || d.status === 'queued');
      if (hasPending && !pollInterval) {
        pollInterval = setInterval(loadDocuments, 2500);
      } else if (!hasPending && pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
      }
    } catch (e) {
      console.error('Error fetching documents:', e);
    }
  }

  // Delete Document
  window.deleteDoc = async function (docId) {
    if (!confirm('Are you sure you want to delete this document and all its indexed embeddings?')) return;
    try {
      await API.deleteDocument(docId);
      showToast('Document deleted successfully', 'success');
      loadDocuments();
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  // Reprocess Document
  window.reprocessDoc = async function (docId) {
    try {
      await API.reprocessDocument(docId);
      showToast('Reprocessing started', 'success');
      loadDocuments();
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  // Upload handler
  async function handleFileUpload(files) {
    if (!files || files.length === 0) return;
    showToast(`Uploading ${files.length} file(s)...`, 'info');
    try {
      const res = await API.uploadFiles(files);
      showToast(res.message, 'success');
      loadDocuments();
    } catch (e) {
      showToast(e.message, 'error');
    }
  }

  // Drag and Drop listeners
  dropzone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (e) => handleFileUpload(e.target.files));

  ['dragenter', 'dragover'].forEach((ev) => {
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach((ev) => {
    dropzone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone.addEventListener('drop', (e) => {
    if (e.dataTransfer.files) {
      handleFileUpload(e.dataTransfer.files);
    }
  });

  // Start New Chat
  async function startNewChat() {
    try {
      const conv = await API.createConversation('New Chat');
      currentConversationId = conv.id;
      convTitle.textContent = conv.title;
      messagesContainer.innerHTML = '';
      showWelcomeScreen();
      showToast('Started new conversation', 'info');
    } catch (e) {
      console.error('Failed to create conversation:', e);
    }
  }

  function showWelcomeScreen() {
    messagesContainer.innerHTML = `
      <div class="welcome-screen">
        <h3>Grounded AI Document Assistant</h3>
        <p>Ask natural-language questions grounded strictly on your uploaded files. All answers include verifiable citations and anti-hallucination checks.</p>
        <div class="quick-prompts">
          <button class="quick-prompt-btn" onclick="window.usePrompt('Summarize the main points across the uploaded documents.')">
            ✨ "Summarize the main points across the uploaded documents."
          </button>
          <button class="quick-prompt-btn" onclick="window.usePrompt('What are the key findings or data mentioned in the files?')">
            🔍 "What are the key findings or data mentioned in the files?"
          </button>
        </div>
      </div>
    `;
  }

  window.usePrompt = function (text) {
    chatInput.value = text;
    chatInput.focus();
    submitQuery();
  };

  // Submit Query with Real-Time SSE
  async function submitQuery() {
    const text = chatInput.value.trim();
    if (!text) return;

    if (!currentConversationId) {
      try {
        const conv = await API.createConversation(text.slice(0, 30));
        currentConversationId = conv.id;
        convTitle.textContent = text.slice(0, 30) + '...';
      } catch (e) {
        console.error('Conversation init failed:', e);
      }
    }

    // Remove welcome screen if present
    const welcome = messagesContainer.querySelector('.welcome-screen');
    if (welcome) welcome.remove();

    // Append User Message Bubble
    appendMessage('user', text);
    chatInput.value = '';
    chatInput.style.height = 'auto';
    sendBtn.disabled = true;

    // Append Assistant Message Shell with Status Container
    const assistantRow = document.createElement('div');
    assistantRow.className = 'message-row assistant';
    assistantRow.innerHTML = `
      <div class="message-avatar">⚡</div>
      <div class="message-content-wrapper">
        <div class="streaming-status">
          <span class="status-pulse"></span>
          <span class="status-text">Analyzing query...</span>
        </div>
        <div class="message-bubble">
          <span class="bubble-text"></span><span class="streaming-cursor"></span>
        </div>
        <div class="citations-wrapper" style="display: none;">
          <div class="citations-header">📚 Referenced Sources</div>
          <div class="citations-grid"></div>
        </div>
      </div>
    `;
    messagesContainer.appendChild(assistantRow);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    const statusEl = assistantRow.querySelector('.status-text');
    const statusContainer = assistantRow.querySelector('.streaming-status');
    const bubbleText = assistantRow.querySelector('.bubble-text');
    const cursor = assistantRow.querySelector('.streaming-cursor');
    const citationsWrapper = assistantRow.querySelector('.citations-wrapper');
    const citationsGrid = assistantRow.querySelector('.citations-grid');

    // Run SSE Stream
    await sseClient.streamQuery({
      message: text,
      conversationId: currentConversationId,
      provider: activeSettings?.default_chat_provider,
      model: activeSettings?.default_chat_model,
      topK: activeSettings?.retrieval_top_k || 4,
      onStatus: (msg) => {
        statusEl.textContent = msg;
      },
      onToken: (tok) => {
        bubbleText.textContent += tok;
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
      },
      onCitations: (citations) => {
        if (citations && citations.length > 0) {
          citationsWrapper.style.display = 'block';
          citationsGrid.innerHTML = citations
            .map(
              (c, i) => `
                <div class="citation-chip" onclick='window.showCitationModal(${JSON.stringify(c).replace(/'/g, "&apos;")})'>
                  <span>[${i + 1}] ${c.filename} (p.${c.page || 1})</span>
                  <span class="score">${Math.round((c.relevance_score || 0) * 100)}% match</span>
                </div>
              `
            )
            .join('');
        }
      },
      onDone: (data) => {
        cursor.remove();
        statusContainer.style.display = 'none';
        sendBtn.disabled = false;
        chatInput.focus();
      },
      onError: (err) => {
        cursor.remove();
        statusContainer.style.display = 'none';
        bubbleText.innerHTML += `<div style="color: var(--status-failed); margin-top: 6px;">⚠️ ${err}</div>`;
        sendBtn.disabled = false;
      },
    });
  }

  function appendMessage(role, content, citations = []) {
    const row = document.createElement('div');
    row.className = `message-row ${role}`;
    row.innerHTML = `
      <div class="message-avatar">${role === 'user' ? '👤' : '⚡'}</div>
      <div class="message-content-wrapper">
        <div class="message-bubble">${content}</div>
      </div>
    `;
    messagesContainer.appendChild(row);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // Citation Modal
  window.showCitationModal = function (c) {
    citationModalBody.innerHTML = `
      <div style="margin-bottom: 12px; font-size: 0.85rem; color: var(--text-secondary);">
        <strong>File:</strong> ${c.filename}<br>
        <strong>Page:</strong> ${c.page || 1}<br>
        <strong>Relevance Score:</strong> ${Math.round((c.relevance_score || 0) * 100)}%
      </div>
      <div style="background: var(--bg-tertiary); padding: 14px; border-radius: var(--radius-md); font-family: var(--font-mono); font-size: 0.82rem; line-height: 1.6; white-space: pre-wrap; color: var(--text-primary); border: 1px solid var(--border-color);">
        ${c.excerpt}
      </div>
    `;
    citationModal.classList.add('active');
  };

  closeCitationBtn.addEventListener('click', () => citationModal.classList.remove('active'));

  // Settings Modal Controls
  openSettingsBtn.addEventListener('click', () => settingsModal.classList.add('active'));
  closeSettingsBtn.addEventListener('click', () => settingsModal.classList.remove('active'));

  topkSlider?.addEventListener('input', (e) => {
    topkVal.textContent = e.target.value;
  });

  saveSettingsBtn.addEventListener('click', async () => {
    try {
      const updated = await API.updateSettings({
        default_chat_provider: providerSelect.value,
        default_chat_model: modelInput.value.trim() || undefined,
        retrieval_top_k: parseInt(topkSlider.value, 10),
      });
      activeSettings.default_chat_provider = updated.active_chat_provider;
      activeSettings.default_chat_model = updated.active_chat_model;
      activeSettings.retrieval_top_k = updated.retrieval_top_k;
      providerBadge.textContent = `${updated.active_chat_provider.toUpperCase()} / ${updated.active_chat_model}`;
      settingsModal.classList.remove('active');
      showToast('Settings saved successfully', 'success');
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  // Form Submit & Keybindings
  chatForm.addEventListener('submit', (e) => {
    e.preventDefault();
    submitQuery();
  });

  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submitQuery();
    }
  });

  chatInput.addEventListener('input', () => {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';
  });

  newChatBtn.addEventListener('click', startNewChat);

  // Initial Load
  loadSettings();
  loadDocuments();
  showWelcomeScreen();
});
