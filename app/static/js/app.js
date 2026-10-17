/**
 * Production RAG Agent UI Controller
 * Featuring Multi-File Room Workspaces, Database Reference Previews,
 * JWT Token Inspector (Access, ID, Refresh), and Persistent Refresh-Resilient State
 */
document.addEventListener('DOMContentLoaded', () => {
  const sseClient = new SSEClient();

  // State
  let currentRoomId = API.getActiveRoomId() || null;
  let currentRoom = null;
  let rooms = [];
  let currentConversationId = localStorage.getItem('rag_active_conv_id') || null;
  let activeDocuments = [];
  let pollInterval = null;
  let activeSettings = null;
  let lastUserQuery = '';

  // DOM Elements - Sidebar
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');
  const docsList = document.getElementById('docs-list');
  const docsCount = document.getElementById('docs-count');
  const newChatBtn = document.getElementById('new-chat-btn');
  const convTitle = document.getElementById('conv-title');
  const convSubtitle = document.getElementById('conv-subtitle');
  const providerBadge = document.getElementById('provider-badge');

  // Sidebar Tabs
  const tabBtnRooms = document.getElementById('tab-btn-rooms');
  const tabBtnDocs = document.getElementById('tab-btn-docs');
  const tabBtnHistory = document.getElementById('tab-btn-history');
  const panelRooms = document.getElementById('panel-rooms');
  const panelDocs = document.getElementById('panel-docs');
  const panelHistory = document.getElementById('panel-history');
  const tabRoomsBadge = document.getElementById('tab-rooms-badge');
  const tabDocsBadge = document.getElementById('tab-docs-badge');
  const tabHistoryBadge = document.getElementById('tab-history-badge');
  const roomsList = document.getElementById('rooms-list');
  const historyList = document.getElementById('history-list');
  const historyCount = document.getElementById('history-count');
  const createRoomBtn = document.getElementById('create-room-btn');

  // Chat Area & Room Banner
  const messagesContainer = document.getElementById('messages-container');
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');
  const sendBtn = document.getElementById('send-btn');
  const bannerRoomName = document.getElementById('banner-room-name');
  const bannerRoomFiles = document.getElementById('banner-room-files');
  const toggleReferencesBtn = document.getElementById('toggle-references-btn');
  const roomReferencesDrawer = document.getElementById('room-references-drawer');
  const refCardsGrid = document.getElementById('ref-cards-grid');
  const refCountBadge = document.getElementById('ref-count-badge');
  const attachFileRoomBtn = document.getElementById('attach-file-room-btn');

  // Auth & User Elements
  const authUserBtn = document.getElementById('auth-user-btn');
  const authAvatarLetter = document.getElementById('auth-avatar-letter');
  const authUsernameLabel = document.getElementById('auth-username-label');
  const authModal = document.getElementById('auth-modal');
  const closeAuthBtn = document.getElementById('close-auth-btn');
  const authTabSignin = document.getElementById('auth-tab-signin');
  const authTabRegister = document.getElementById('auth-tab-register');
  const authTabTokens = document.getElementById('auth-tab-tokens');
  const authPanelSignin = document.getElementById('auth-panel-signin');
  const authPanelRegister = document.getElementById('auth-panel-register');
  const authPanelTokens = document.getElementById('auth-panel-tokens');
  const loginForm = document.getElementById('login-form');
  const registerForm = document.getElementById('register-form');
  const demoLoginBtn = document.getElementById('demo-login-btn');
  const logoutBtn = document.getElementById('logout-btn');
  const refreshNowBtn = document.getElementById('refresh-now-btn');
  const rawAccessToken = document.getElementById('raw-access-token');
  const rawIdToken = document.getElementById('raw-id-token');
  const rawRefreshToken = document.getElementById('raw-refresh-token');
  const idTokenClaims = document.getElementById('id-token-claims');

  // Room Modal Elements
  const roomModal = document.getElementById('room-modal');
  const closeRoomBtn = document.getElementById('close-room-btn');
  const cancelRoomBtn = document.getElementById('cancel-room-btn');
  const createRoomForm = document.getElementById('create-room-form');
  const roomNameInput = document.getElementById('room-name-input');
  const roomDescInput = document.getElementById('room-desc-input');
  const roomDocCheckboxes = document.getElementById('room-doc-checkboxes');

  // Settings & Citation Modals
  const openSettingsBtn = document.getElementById('open-settings-btn');
  const settingsModal = document.getElementById('settings-modal');
  const closeSettingsBtn = document.getElementById('close-settings-btn');
  const saveSettingsBtn = document.getElementById('save-settings-btn');
  const providerSelect = document.getElementById('provider-select');
  const modelInput = document.getElementById('model-input');
  const embeddingProviderSelect = document.getElementById('embedding-provider-select');
  const embeddingModelInput = document.getElementById('embedding-model-input');
  const topkSlider = document.getElementById('topk-slider');
  const topkVal = document.getElementById('topk-val');
  const citationModal = document.getElementById('citation-modal');
  const closeCitationBtn = document.getElementById('close-citation-btn');
  const citationModalBody = document.getElementById('citation-modal-body');
  const toastContainer = document.getElementById('toast-container');

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
    toast.innerHTML = `<span>${type === 'error' ? '⚠️' : '✓'}</span><span>${escapeHtml(message)}</span>`;
    toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      setTimeout(() => toast.remove(), 250);
    }, 4000);
  }

  // Escape HTML utility
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Decode JWT payload without library for display in Inspector
  function parseJwtPayload(token) {
    if (!token) return null;
    try {
      const base64Url = token.split('.')[1];
      const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
      const jsonPayload = decodeURIComponent(
        atob(base64)
          .split('')
          .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
          .join('')
      );
      return JSON.parse(jsonPayload);
    } catch {
      return null;
    }
  }

  // --------------------------------------------------------------------------
  // Performance Utilities: requestAnimationFrame smooth scrolling & memoization
  // --------------------------------------------------------------------------
  let scrollScheduled = false;
  function scheduleScrollToBottom(immediate = false) {
    if (immediate) {
      messagesContainer.scrollTop = messagesContainer.scrollHeight;
      return;
    }
    if (!scrollScheduled) {
      scrollScheduled = true;
      requestAnimationFrame(() => {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        scrollScheduled = false;
      });
    }
  }

  // --------------------------------------------------------------------------
  // Rich Markdown Renderer with Code Blocks, Tables, and Inline Citations
  // --------------------------------------------------------------------------
  const markdownCache = new Map();

  function renderMarkdown(rawText, citations = []) {
    if (!rawText) return '';

    // Cache lookup for fast historical re-rendering
    const cacheKey = rawText.length < 800 ? `${rawText}:${citations.length}` : null;
    if (cacheKey && markdownCache.has(cacheKey)) {
      return markdownCache.get(cacheKey);
    }

    let text = rawText;

    // 1. Extract and preserve code blocks
    const codeBlocks = [];
    text = text.replace(/```([a-zA-Z0-9_-]*)\r?\n([\s\S]*?)```/g, (match, lang, code) => {
      const placeholder = `__CODE_BLOCK_${codeBlocks.length}__`;
      codeBlocks.push({
        lang: lang.trim() || 'plaintext',
        code: code.trimEnd(),
      });
      return placeholder;
    });

    // 2. Extract and preserve markdown tables
    const tables = [];
    text = text.replace(/((?:^|\n)\|[^\n]+\|\r?\n\|[-:\s|]+\|\r?\n(?:\|[^\n]+\|\r?\n?)+)/g, (match) => {
      const placeholder = `__TABLE_BLOCK_${tables.length}__`;
      tables.push(match.trim());
      return '\n\n' + placeholder + '\n\n';
    });

    // 3. Escape HTML
    text = escapeHtml(text);

    // 4. Blockquotes
    text = text.replace(/^>\s?(.*)$/gm, '<blockquote>$1</blockquote>');

    // 5. Headings
    text = text.replace(/^#### (.*$)/gm, '<h4>$1</h4>');
    text = text.replace(/^### (.*$)/gm, '<h3>$1</h3>');
    text = text.replace(/^## (.*$)/gm, '<h2>$1</h2>');
    text = text.replace(/^# (.*$)/gm, '<h1>$1</h1>');

    // 6. Bold & Italic
    text = text.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
    text = text.replace(/__(.*?)__/g, '<strong>$1</strong>');
    text = text.replace(/_(.*?)_/g, '<em>$1</em>');

    // 7. Inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 8. Citations inline reference: [1], [2], etc.
    if (citations && citations.length > 0) {
      text = text.replace(/\[(\d+)\]/g, (match, num) => {
        const idx = parseInt(num, 10) - 1;
        const citation = citations[idx];
        if (citation) {
          const safeCitation = JSON.stringify(citation).replace(/"/g, '&quot;');
          return `<span class="inline-citation" onclick='window.showCitationModal(${safeCitation})' title="${escapeHtml(citation.filename)} (Page ${citation.page || 1})">[${num}]</span>`;
        }
        return match;
      });
    }

    // 9. Unordered Lists
    text = text.replace(/^[-*•]\s+(.*)$/gm, '<li>$1</li>');
    text = text.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

    // 10. Ordered Lists
    text = text.replace(/^\d+\.\s+(.*)$/gm, '<li class="ol-item">$1</li>');
    text = text.replace(/(<li class="ol-item">.*<\/li>\n?)+/g, '<ol>$&</ol>');

    // 11. Links
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    // 12. Paragraphs & Line Breaks
    text = text.replace(/\n\n+/g, '</p><p>');
    text = `<p>${text}</p>`;
    text = text.replace(/<p><\/p>/g, '');
    text = text.replace(/<p>(<h[1-4]>)/g, '$1');
    text = text.replace(/(<\/h[1-4]>)<\/p>/g, '$1');
    text = text.replace(/<p>(<ul|<ol|<blockquote>)/g, '$1');
    text = text.replace(/(<\/ul>|<\/ol>|<\/blockquote>)<\/p>/g, '$1');

    // 13. Reinsert Tables
    tables.forEach((rawTable, i) => {
      const rows = rawTable.split('\n').filter((r) => r.trim().startsWith('|'));
      if (rows.length >= 2) {
        const headerCells = rows[0].split('|').slice(1, -1).map((c) => c.trim());
        const bodyRows = rows.slice(2).map((r) => r.split('|').slice(1, -1).map((c) => c.trim()));

        let tableHtml = `<div class="markdown-table-wrapper"><table class="markdown-table"><thead><tr>`;
        headerCells.forEach((h) => {
          tableHtml += `<th>${escapeHtml(h)}</th>`;
        });
        tableHtml += `</tr></thead><tbody>`;

        bodyRows.forEach((row) => {
          tableHtml += `<tr>`;
          row.forEach((cell) => {
            tableHtml += `<td>${escapeHtml(cell)}</td>`;
          });
          tableHtml += `</tr>`;
        });
        tableHtml += `</tbody></table></div>`;

        text = text.replace(`__TABLE_BLOCK_${i}__`, tableHtml);
      } else {
        text = text.replace(`__TABLE_BLOCK_${i}__`, `<pre>${escapeHtml(rawTable)}</pre>`);
      }
    });

    // 14. Reinsert Code Blocks with Copy Button
    codeBlocks.forEach((item, i) => {
      const codeId = `code-block-${Date.now()}-${i}-${Math.floor(Math.random() * 1000)}`;
      const escapedCode = escapeHtml(item.code);
      const blockHtml = `
        <div class="code-block-container" id="${codeId}">
          <div class="code-block-header">
            <span class="code-lang-label">
              <span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--accent-primary);"></span>
              ${escapeHtml(item.lang)}
            </span>
            <button class="code-copy-btn" onclick="window.copyCode(this, '${codeId}')" title="Copy code snippet">
              <span class="copy-icon">📋</span>
              <span class="copy-label">Copy</span>
            </button>
          </div>
          <pre><code class="language-${escapeHtml(item.lang)}">${escapedCode}</code></pre>
        </div>
      `;
      text = text.replace(`__CODE_BLOCK_${i}__`, blockHtml);
    });

    if (cacheKey) {
      if (markdownCache.size > 200) {
        const oldestKey = markdownCache.keys().next().value;
        markdownCache.delete(oldestKey);
      }
      markdownCache.set(cacheKey, text);
    }

    return text;
  }

  // --------------------------------------------------------------------------
  // Response Classifier
  // --------------------------------------------------------------------------
  function classifyResponse(content, meta = {}, citations = []) {
    let responseType = meta.response_type;

    if (!responseType) {
      if (meta.intent === 'greeting') {
        responseType = 'greeting';
      } else if (
        content.includes('do not contain sufficient information') ||
        content.includes('Please upload relevant files') ||
        meta.is_relevant === false
      ) {
        responseType = 'insufficient_info';
      } else if (citations && citations.length > 0) {
        responseType = 'grounded';
      } else {
        responseType = 'general';
      }
    }

    const configs = {
      grounded: {
        badgeClass: 'grounded',
        badgeIcon: '🛡️',
        badgeText: 'GROUNDED ANSWER',
        avatarIcon: '🛡️',
        avatarClass: 'grounded',
      },
      insufficient_info: {
        badgeClass: 'insufficient',
        badgeIcon: '⚠️',
        badgeText: 'INSUFFICIENT INFORMATION',
        avatarIcon: '⚠️',
        avatarClass: 'insufficient_info',
      },
      greeting: {
        badgeClass: 'greeting',
        badgeIcon: '✨',
        badgeText: 'CONVERSATIONAL GREETING',
        avatarIcon: '✨',
        avatarClass: 'greeting',
      },
      general: {
        badgeClass: 'general',
        badgeIcon: '💡',
        badgeText: 'GENERAL SYNTHESIS',
        avatarIcon: '⚡',
        avatarClass: '',
      },
      error: {
        badgeClass: 'error',
        badgeIcon: '❌',
        badgeText: 'EXECUTION ERROR',
        avatarIcon: '❌',
        avatarClass: 'insufficient_info',
      },
    };

    return configs[responseType] || configs.general;
  }

  // --------------------------------------------------------------------------
  // Assistant Message Renderer
  // --------------------------------------------------------------------------
  function renderAssistantMessage({ content, citations = [], meta = {}, timestamp }) {
    const config = classifyResponse(content, meta, citations);
    const row = document.createElement('div');
    row.className = 'message-row assistant';

    let badgesHtml = `
      <div class="message-meta-header">
        <span class="response-type-pill ${config.badgeClass}">
          <span>${config.badgeIcon}</span>
          <span>${config.badgeText}</span>
        </span>
    `;

    if (meta.provider && meta.model) {
      badgesHtml += `
        <span class="response-model-tag">
          ${escapeHtml(meta.provider.toUpperCase())} / ${escapeHtml(meta.model)}
        </span>
      `;
    }

    if (meta.retrieval_retry_count && meta.retrieval_retry_count > 0) {
      badgesHtml += `
        <span class="meta-tag-pill" title="Query was automatically rewritten and re-retrieved">
          🔄 ${meta.retrieval_retry_count} retries
        </span>
      `;
    }

    badgesHtml += `</div>`;

    let citationsHtml = '';
    if (citations && citations.length > 0) {
      citationsHtml = `
        <div class="citations-section">
          <div class="citations-header">
            <span>📚 Verified Sources (${citations.length})</span>
          </div>
          <div class="citation-pills-row">
            ${citations
              .map((c, i) => {
                const safeCitation = JSON.stringify(c).replace(/"/g, '&quot;');
                const matchPct = Math.round((c.relevance_score || 0) * 100);
                return `
                  <div class="citation-pill" onclick='window.showCitationModal(${safeCitation})' title="${escapeHtml(c.excerpt || '')}">
                    <span class="citation-pill-index">[${i + 1}]</span>
                    <span class="citation-pill-name">${escapeHtml(c.filename)}</span>
                    <span class="citation-pill-page">p.${c.page || 1}</span>
                    ${matchPct > 0 ? `<span class="citation-pill-score">${matchPct}%</span>` : ''}
                  </div>
                `;
              })
              .join('')}
          </div>
        </div>
      `;
    }

    const htmlBody = renderMarkdown(content, citations);

    row.innerHTML = `
      <div class="message-avatar ${config.avatarClass}">${config.avatarIcon}</div>
      <div class="message-content-wrapper">
        ${badgesHtml}
        <div class="message-bubble">
          <div class="bubble-markdown">${htmlBody}</div>
          ${citationsHtml}
        </div>
        <div class="message-actions-bar">
          <div class="msg-action-time">${timestamp ? new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</div>
          <div class="msg-action-buttons">
            <button class="msg-action-btn" onclick="window.copyAnswer(this)" title="Copy entire response">
              <span>📋</span> Copy
            </button>
            <button class="msg-action-btn" onclick="window.retryLastQuery()" title="Regenerate this response">
              <span>🔄</span> Retry
            </button>
          </div>
        </div>
      </div>
    `;

    messagesContainer.appendChild(row);
    scheduleScrollToBottom(true);
  }

  // --------------------------------------------------------------------------
  // Authentication & JWT Management
  // --------------------------------------------------------------------------
  function updateAuthUI() {
    const user = API.getCurrentUser();
    const accessToken = API.getAccessToken();
    const idToken = API.getIdToken();
    const refreshToken = API.getRefreshToken();

    if (user && accessToken) {
      authUsernameLabel.textContent = user.username || user.email;
      authAvatarLetter.textContent = (user.username || user.email)[0].toUpperCase();
      authUserBtn.title = `Signed in as ${user.email} (${user.role})`;
      logoutBtn.style.display = 'inline-block';
    } else {
      authUsernameLabel.textContent = 'Sign In';
      authAvatarLetter.textContent = '👤';
      authUserBtn.title = 'Click to Sign In or Register';
      logoutBtn.style.display = 'none';
    }

    // Populate Token Inspector
    if (rawAccessToken) rawAccessToken.textContent = accessToken || 'None (Not signed in)';
    if (rawIdToken) rawIdToken.textContent = idToken || 'None (Not signed in)';
    if (rawRefreshToken) rawRefreshToken.textContent = refreshToken || 'None (Not signed in)';

    if (idToken && idTokenClaims) {
      const claims = parseJwtPayload(idToken);
      if (claims) {
        idTokenClaims.innerHTML = Object.entries(claims)
          .map(
            ([k, v]) =>
              `<span class="token-claim-badge"><strong>${escapeHtml(k)}:</strong> ${escapeHtml(String(v))}</span>`
          )
          .join('');
      } else {
        idTokenClaims.innerHTML = '';
      }
    } else if (idTokenClaims) {
      idTokenClaims.innerHTML = '';
    }
  }

  function switchAuthTab(tabName) {
    [authTabSignin, authTabRegister, authTabTokens].forEach((t) => t?.classList.remove('active'));
    [authPanelSignin, authPanelRegister, authPanelTokens].forEach((p) => {
      if (p) p.style.display = 'none';
    });

    if (tabName === 'signin') {
      authTabSignin?.classList.add('active');
      if (authPanelSignin) authPanelSignin.style.display = 'block';
    } else if (tabName === 'register') {
      authTabRegister?.classList.add('active');
      if (authPanelRegister) authPanelRegister.style.display = 'block';
    } else if (tabName === 'tokens') {
      authTabTokens?.classList.add('active');
      if (authPanelTokens) authPanelTokens.style.display = 'block';
      updateAuthUI();
    }
  }

  authTabSignin?.addEventListener('click', () => switchAuthTab('signin'));
  authTabRegister?.addEventListener('click', () => switchAuthTab('register'));
  authTabTokens?.addEventListener('click', () => switchAuthTab('tokens'));

  authUserBtn?.addEventListener('click', () => {
    const user = API.getCurrentUser();
    switchAuthTab(user ? 'tokens' : 'signin');
    authModal?.classList.add('active');
  });

  closeAuthBtn?.addEventListener('click', () => authModal?.classList.remove('active'));

  loginForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const u = document.getElementById('login-username').value.trim();
    const p = document.getElementById('login-password').value;
    try {
      showToast('Authenticating...', 'info');
      await API.login(u, p);
      showToast('Successfully signed in!', 'success');
      authModal?.classList.remove('active');
      updateAuthUI();
      loadRooms();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  registerForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('reg-email').value.trim();
    const u = document.getElementById('reg-username').value.trim();
    const fn = document.getElementById('reg-fullname').value.trim();
    const p = document.getElementById('reg-password').value;
    try {
      showToast('Creating account...', 'info');
      await API.register(email, u, p, fn);
      showToast('Account created and signed in!', 'success');
      authModal?.classList.remove('active');
      updateAuthUI();
      loadRooms();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  demoLoginBtn?.addEventListener('click', async () => {
    try {
      showToast('Logging in with Demo Account...', 'info');
      try {
        await API.login('demo_user', 'demo123456');
      } catch {
        // If not created yet, register it
        await API.register('demo@ragagent.local', 'demo_user', 'demo123456', 'Demo User');
      }
      showToast('Demo User authenticated!', 'success');
      authModal?.classList.remove('active');
      updateAuthUI();
      loadRooms();
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  logoutBtn?.addEventListener('click', async () => {
    await API.logout();
    showToast('Signed out', 'info');
    authModal?.classList.remove('active');
    updateAuthUI();
    loadRooms();
  });

  refreshNowBtn?.addEventListener('click', async () => {
    showToast('Refreshing tokens...', 'info');
    const success = await API.refreshAuth();
    if (success) {
      showToast('Tokens successfully refreshed & rotated!', 'success');
      updateAuthUI();
    } else {
      showToast('Failed to refresh tokens. Please log in again.', 'error');
    }
  });

  window.copyToken = function (type) {
    let token = '';
    if (type === 'access') token = API.getAccessToken();
    else if (type === 'id') token = API.getIdToken();
    else if (type === 'refresh') token = API.getRefreshToken();

    if (!token) return showToast('No token available to copy', 'error');
    navigator.clipboard.writeText(token).then(() => {
      showToast(`${type.toUpperCase()} token copied to clipboard`, 'success');
    });
  };

  // --------------------------------------------------------------------------
  // Multi-File Room Workspaces & Database References
  // --------------------------------------------------------------------------
  async function loadRooms() {
    try {
      const data = await API.getRooms();
      rooms = data || [];
      if (tabRoomsBadge) tabRoomsBadge.textContent = rooms.length;

      // If no rooms exist, automatically create default General Workspace
      if (rooms.length === 0) {
        try {
          const defaultRoom = await API.createRoom('General Workspace', 'Default workspace for uploaded documents');
          rooms = [defaultRoom];
          if (tabRoomsBadge) tabRoomsBadge.textContent = 1;
        } catch (e) {
          console.warn('Auto room creation error:', e);
        }
      }

      renderRoomsList();

      // Ensure active room is selected and restored
      if (!currentRoomId || !rooms.find((r) => r.id === currentRoomId)) {
        if (rooms.length > 0) {
          selectRoom(rooms[0].id, false);
        }
      } else {
        selectRoom(currentRoomId, false);
      }
    } catch (err) {
      console.error('Failed to load rooms:', err);
    }
  }

  function renderRoomsList() {
    if (!roomsList) return;
    if (rooms.length === 0) {
      roomsList.innerHTML = `
        <div style="text-align: center; padding: 24px 10px; color: var(--text-muted); font-size: 0.82rem;">
          No workspaces yet.<br>Click "+ New Room" above to create one.
        </div>
      `;
      return;
    }

    roomsList.innerHTML = rooms
      .map((r) => {
        const isActive = r.id === currentRoomId;
        const time = new Date(r.updated_at).toLocaleDateString([], {
          month: 'short',
          day: 'numeric',
        });

        return `
          <div class="room-card ${isActive ? 'active' : ''}" onclick="window.selectRoom('${r.id}', true)">
            <div class="room-card-header">
              <span class="room-title" title="${escapeHtml(r.name)}">${escapeHtml(r.name)}</span>
              ${isActive ? '<span class="room-badge-active">ACTIVE</span>' : ''}
            </div>
            ${r.description ? `<div class="room-desc">${escapeHtml(r.description)}</div>` : ''}
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

  window.selectRoom = async function (roomId, switchTab = false) {
    currentRoomId = roomId;
    API.setActiveRoomId(roomId);

    // Update URL without page reload for easy bookmarking/sharing
    const url = new URL(window.location);
    url.searchParams.set('room', roomId);
    window.history.replaceState({}, '', url);

    renderRoomsList();

    try {
      const room = await API.getRoom(roomId);
      currentRoom = room;

      // Update Top Banner
      if (bannerRoomName) bannerRoomName.textContent = room.name;
      if (convTitle) convTitle.textContent = room.name;
      if (convSubtitle) convSubtitle.textContent = room.description || 'Strictly grounded answers with verifiable source attribution';

      // Update Attached Document Pills
      if (bannerRoomFiles) {
        if (!room.documents || room.documents.length === 0) {
          bannerRoomFiles.innerHTML = `<span style="font-size: 0.72rem; color: var(--text-muted);">No files attached</span>`;
        } else {
          bannerRoomFiles.innerHTML = room.documents
            .map(
              (d) => `
              <span class="room-file-pill" title="${escapeHtml(d.filename)} (${d.chunk_count} chunks)">
                <span>${iconMap[d.file_type] || '📄'}</span>
                <span>${escapeHtml(d.filename)}</span>
                <span style="opacity: 0.6; cursor: pointer;" onclick="window.detachDocFromRoom('${room.id}', '${d.id}', event)" title="Detach file from room">×</span>
              </span>
            `
            )
            .join('');
        }
      }

      // Update Database References Drawer
      renderRoomReferences(room.references || []);

      // Load conversation messages
      currentConversationId = room.active_conversation_id;
      if (currentConversationId) {
        localStorage.setItem('rag_active_conv_id', currentConversationId);
        loadConversationMessages(currentConversationId);
      } else {
        showWelcomeScreen();
      }

      loadConversations();
    } catch (err) {
      console.error('Error fetching room details:', err);
    }
  };

  function renderRoomReferences(refs) {
    if (refCountBadge) refCountBadge.textContent = refs.length;
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
        <div class="ref-card" onclick="window.usePrompt('Summarize key details from ${escapeHtml(ref.filename)} regarding: ${escapeHtml(ref.excerpt).replace(/'/g, "\\'")}')" title="Click to ask question about this reference">
          <div class="ref-card-header">
            <span>📄 ${escapeHtml(ref.filename)}</span>
            <span>p. ${ref.page || 1}</span>
          </div>
          <div class="ref-card-snippet">
            ${escapeHtml(ref.excerpt)}
          </div>
        </div>
      `
      )
      .join('');
  }

  toggleReferencesBtn?.addEventListener('click', () => {
    if (!roomReferencesDrawer) return;
    const isHidden = roomReferencesDrawer.style.display === 'none';
    roomReferencesDrawer.style.display = isHidden ? 'block' : 'none';
  });

  attachFileRoomBtn?.addEventListener('click', () => {
    switchSidebarTab('docs');
    fileInput?.click();
  });

  window.deleteRoom = async function (roomId, ev) {
    if (ev) ev.stopPropagation();
    if (!confirm('Are you sure you want to delete this workspace room?')) return;
    try {
      await API.deleteRoom(roomId);
      showToast('Room deleted', 'info');
      currentRoomId = null;
      API.setActiveRoomId(null);
      loadRooms();
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  window.detachDocFromRoom = async function (roomId, docId, ev) {
    if (ev) ev.stopPropagation();
    try {
      await API.detachDocumentFromRoom(roomId, docId);
      showToast('Document detached from room', 'info');
      selectRoom(roomId, false);
    } catch (err) {
      showToast(err.message, 'error');
    }
  };

  // --------------------------------------------------------------------------
  // Create Room Modal Handlers
  // --------------------------------------------------------------------------
  createRoomBtn?.addEventListener('click', () => {
    if (roomDocCheckboxes) {
      if (activeDocuments.length === 0) {
        roomDocCheckboxes.innerHTML = `<span style="font-size: 0.75rem; color: var(--text-muted);">No indexed documents in library yet.</span>`;
      } else {
        roomDocCheckboxes.innerHTML = activeDocuments
          .map(
            (d) => `
            <label style="display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 0.78rem; cursor: pointer; color: var(--text-primary);">
              <input type="checkbox" name="room_docs" value="${d.id}" checked>
              <span>${iconMap[d.file_type] || '📄'} ${escapeHtml(d.filename)} (${d.chunk_count} chunks)</span>
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
      showToast('Creating workspace room...', 'info');
      const room = await API.createRoom(name, desc);

      // Attach checked documents concurrently
      const checked = roomDocCheckboxes?.querySelectorAll('input[name="room_docs"]:checked');
      if (checked && checked.length > 0) {
        await Promise.all(Array.from(checked).map((input) => API.attachDocumentToRoom(room.id, input.value).catch(() => {})));
      }

      showToast(`Room '${name}' created!`, 'success');
      roomModal?.classList.remove('active');
      createRoomForm.reset();
      await loadRooms();
      selectRoom(room.id, true);
    } catch (err) {
      showToast(err.message, 'error');
    }
  });

  // --------------------------------------------------------------------------
  // Document Loading and File Uploads
  // --------------------------------------------------------------------------
  async function loadDocuments() {
    try {
      const data = await API.getDocuments();
      activeDocuments = data.items || [];
      if (docsCount) docsCount.textContent = `${activeDocuments.length} files`;
      if (tabDocsBadge) tabDocsBadge.textContent = activeDocuments.length;

      // Auto-attach unattached documents to default room concurrently if room has no documents
      if (currentRoom && (!currentRoom.documents || currentRoom.documents.length === 0) && activeDocuments.length > 0 && !window._hasAutoAttached) {
        window._hasAutoAttached = true;
        await Promise.all(activeDocuments.map((d) => API.attachDocumentToRoom(currentRoom.id, d.id).catch(() => {})));
        const updatedRoom = await API.getRoom(currentRoom.id);
        currentRoom = updatedRoom;
        selectRoom(currentRoom.id, false);
      }

      if (activeDocuments.length === 0) {
        docsList.innerHTML = `
          <div style="text-align: center; padding: 28px 10px; color: var(--text-muted); font-size: 0.82rem;">
            No documents indexed yet.<br>Drag and drop files above to start.
          </div>
        `;
        return;
      }

      docsList.innerHTML = activeDocuments
        .map((doc) => {
          const icon = iconMap[doc.file_type] || '📄';
          const sizeKb = Math.round(doc.file_size / 1024);
          const isProcessing = doc.status === 'processing' || doc.status === 'queued';

          return `
            <div class="doc-card" id="doc-${doc.id}">
              <div class="doc-card-top">
                <div class="doc-info" title="${escapeHtml(doc.filename)}">
                  <span class="doc-icon">${icon}</span>
                  <span class="doc-name">${escapeHtml(doc.filename)}</span>
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
              ${doc.error_message ? `<div style="margin-top: 6px; font-size: 0.7rem; color: var(--status-failed); line-height: 1.3;">${escapeHtml(doc.error_message)}</div>` : ''}
            </div>
          `;
        })
        .join('');

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

  // File Upload handler (uploads to active room if selected)
  async function handleFileUpload(files) {
    if (!files || files.length === 0) return;
    showToast(`Uploading ${files.length} file(s)...`, 'info');
    try {
      if (currentRoomId) {
        const res = await API.uploadFilesToRoom(currentRoomId, files);
        showToast(res.message, 'success');
      } else {
        const res = await API.uploadFiles(files);
        showToast(res.message, 'success');
      }
      await loadDocuments();
      if (currentRoomId) selectRoom(currentRoomId, false);
    } catch (e) {
      showToast(e.message, 'error');
    }
  }

  dropzone?.addEventListener('click', () => fileInput?.click());
  fileInput?.addEventListener('change', (e) => handleFileUpload(e.target.files));

  ['dragenter', 'dragover'].forEach((ev) => {
    dropzone?.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach((ev) => {
    dropzone?.addEventListener(ev, (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
    });
  });

  dropzone?.addEventListener('drop', (e) => {
    if (e.dataTransfer.files) {
      handleFileUpload(e.dataTransfer.files);
    }
  });

  window.deleteDoc = async function (docId) {
    if (!confirm('Are you sure you want to delete this document and all its indexed embeddings?')) return;
    try {
      await API.deleteDocument(docId);
      showToast('Document deleted successfully', 'success');
      loadDocuments();
      if (currentRoomId) selectRoom(currentRoomId, false);
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  window.reprocessDoc = async function (docId) {
    try {
      await API.reprocessDocument(docId);
      showToast('Reprocessing started', 'success');
      loadDocuments();
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  // --------------------------------------------------------------------------
  // Sidebar Tabs Navigation
  // --------------------------------------------------------------------------
  tabBtnRooms?.addEventListener('click', () => switchSidebarTab('rooms'));
  tabBtnDocs?.addEventListener('click', () => switchSidebarTab('docs'));
  tabBtnHistory?.addEventListener('click', () => switchSidebarTab('history'));

  function switchSidebarTab(tabName) {
    [tabBtnRooms, tabBtnDocs, tabBtnHistory].forEach((b) => b?.classList.remove('active'));
    [panelRooms, panelDocs, panelHistory].forEach((p) => p?.classList.remove('active'));

    if (tabName === 'rooms') {
      tabBtnRooms?.classList.add('active');
      panelRooms?.classList.add('active');
      loadRooms();
    } else if (tabName === 'docs') {
      tabBtnDocs?.classList.add('active');
      panelDocs?.classList.add('active');
      loadDocuments();
    } else {
      tabBtnHistory?.classList.add('active');
      panelHistory?.classList.add('active');
      loadConversations();
    }
  }

  // --------------------------------------------------------------------------
  // Conversation History
  // --------------------------------------------------------------------------
  async function loadConversations() {
    try {
      const convs = await API.getConversations(currentRoomId);
      if (tabHistoryBadge) tabHistoryBadge.textContent = convs.length;
      if (historyCount) historyCount.textContent = `${convs.length} sessions`;

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
          const isActive = c.id === currentConversationId;
          const time = new Date(c.updated_at).toLocaleDateString([], {
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
          });

          return `
            <div class="history-card ${isActive ? 'active' : ''}" onclick="window.selectConversation('${c.id}')">
              <div class="history-card-header">
                <span class="history-title" title="${escapeHtml(c.title)}">${escapeHtml(c.title)}</span>
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
    try {
      const conv = await API.getConversation(convId);
      currentConversationId = conv.id;
      localStorage.setItem('rag_active_conv_id', conv.id);
      messagesContainer.innerHTML = '';

      if (!conv.messages || conv.messages.length === 0) {
        showWelcomeScreen();
      } else {
        conv.messages.forEach((msg) => {
          if (msg.role === 'user') {
            appendMessage('user', msg.content);
          } else {
            renderAssistantMessage({
              content: msg.content,
              citations: msg.citations || [],
              meta: msg.metadata_info || {},
              timestamp: msg.created_at,
            });
          }
        });
      }
    } catch (e) {
      console.warn('Failed to load messages for conversation:', e);
      showWelcomeScreen();
    }
  }

  window.selectConversation = function (convId) {
    if (convId === currentConversationId) return;
    loadConversationMessages(convId);
    loadConversations();
  };

  window.deleteConversation = async function (convId, ev) {
    if (ev) ev.stopPropagation();
    if (!confirm('Are you sure you want to delete this chat session?')) return;
    try {
      await API.deleteConversation(convId);
      showToast('Conversation deleted', 'info');
      if (currentConversationId === convId) {
        startNewChat();
      } else {
        loadConversations();
      }
    } catch (e) {
      showToast(e.message, 'error');
    }
  };

  async function startNewChat() {
    try {
      const title = currentRoom ? `${currentRoom.name} Chat` : 'New Chat';
      const conv = await API.createConversation(title, currentRoomId);
      currentConversationId = conv.id;
      localStorage.setItem('rag_active_conv_id', conv.id);
      messagesContainer.innerHTML = '';
      showWelcomeScreen();
      showToast('Started new conversation thread', 'info');
      loadConversations();
    } catch (e) {
      console.error('Failed to create conversation:', e);
    }
  }

  newChatBtn?.addEventListener('click', startNewChat);

  function showWelcomeScreen() {
    const fileCount = currentRoom?.documents?.length || 0;
    const roomTitle = currentRoom?.name || 'Workspace';

    messagesContainer.innerHTML = `
      <div class="welcome-screen">
        <h3>${escapeHtml(roomTitle)} — Grounded AI Assistant</h3>
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

  window.usePrompt = function (text) {
    chatInput.value = text;
    chatInput.focus();
    submitQuery();
  };

  window.retryLastQuery = function () {
    if (lastUserQuery) {
      chatInput.value = lastUserQuery;
      submitQuery();
    }
  };

  function appendMessage(role, content) {
    const row = document.createElement('div');
    row.className = `message-row ${role}`;
    row.innerHTML = `
      <div class="message-avatar">${role === 'user' ? '👤' : '⚡'}</div>
      <div class="message-content-wrapper">
        <div class="message-bubble">${escapeHtml(content)}</div>
      </div>
    `;
    messagesContainer.appendChild(row);
    scheduleScrollToBottom(true);
  }

  // --------------------------------------------------------------------------
  // Submit Query with Real-Time SSE Stream & Room Document Scoping
  // --------------------------------------------------------------------------
  async function submitQuery() {
    const text = chatInput.value.trim();
    if (!text) return;
    lastUserQuery = text;

    // Remove welcome screen
    const welcome = messagesContainer.querySelector('.welcome-screen');
    if (welcome) welcome.remove();

    appendMessage('user', text);
    chatInput.value = '';
    chatInput.style.height = 'auto';
    sendBtn.disabled = true;

    // Append Assistant Streaming Shell
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
    scheduleScrollToBottom(true);

    const avatarEl = assistantRow.querySelector('.message-avatar');
    const statusEl = assistantRow.querySelector('.status-text');
    const bubbleText = assistantRow.querySelector('.bubble-text');

    let accumulatedContent = '';
    let currentCitations = [];
    let receivedMeta = {};

    // Get documents belonging to current room
    const roomDocIds = currentRoom?.documents?.map((d) => d.id) || null;

    // Run SSE Stream
    await sseClient.streamQuery({
      message: text,
      conversationId: currentConversationId,
      roomId: currentRoomId,
      documentIds: roomDocIds,
      provider: activeSettings?.default_chat_provider,
      model: activeSettings?.default_chat_model,
      topK: activeSettings?.retrieval_top_k || 4,
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
        scheduleScrollToBottom();
      },
      onCitations: (citations) => {
        currentCitations = citations || [];
      },
      onDone: (data) => {
        sendBtn.disabled = false;
        chatInput.focus();

        const finalCitations = (data && data.citations) || currentCitations;
        const finalMeta = Object.assign({}, receivedMeta, data || {});

        assistantRow.remove();
        renderAssistantMessage({
          content: accumulatedContent || data?.answer || '',
          citations: finalCitations,
          meta: finalMeta,
          timestamp: new Date().toISOString(),
        });

        loadConversations();
      },
      onError: (err) => {
        sendBtn.disabled = false;
        assistantRow.remove();
        renderAssistantMessage({
          content: `An error occurred: ${err}`,
          citations: [],
          meta: { response_type: 'error' },
          timestamp: new Date().toISOString(),
        });
      },
    });
  }

  // --------------------------------------------------------------------------
  // Global Actions: Copy, Citation Modal
  // --------------------------------------------------------------------------
  window.copyCode = function (btn, codeId) {
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
  };

  window.copyAnswer = function (btn) {
    const wrapper = btn.closest('.message-content-wrapper');
    if (!wrapper) return;
    const markdownEl = wrapper.querySelector('.bubble-markdown');
    if (!markdownEl) return;
    const textToCopy = markdownEl.innerText || markdownEl.textContent;

    navigator.clipboard.writeText(textToCopy).then(() => {
      const origHtml = btn.innerHTML;
      btn.innerHTML = '<span>✓</span> Copied!';
      btn.classList.add('copied');
      showToast('Answer copied to clipboard', 'success');
      setTimeout(() => {
        btn.innerHTML = origHtml;
        btn.classList.remove('copied');
      }, 2000);
    });
  };

  window.showCitationModal = function (c) {
    citationModalBody.innerHTML = `
      <div style="margin-bottom: 12px; font-size: 0.85rem; color: var(--text-secondary); line-height: 1.6;">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
          <strong>📄 ${escapeHtml(c.filename)}</strong>
          <span class="citation-match-pill">${Math.round((c.relevance_score || 0) * 100)}% match</span>
        </div>
        <div><strong>Page:</strong> ${c.page || 1} • <strong>Chunk ID:</strong> ${escapeHtml(c.chunk_id || 'N/A')}</div>
      </div>
      <div style="background: var(--bg-tertiary); padding: 14px; border-radius: var(--radius-md); font-family: var(--font-mono); font-size: 0.82rem; line-height: 1.6; white-space: pre-wrap; color: var(--text-primary); border: 1px solid var(--border-color); max-height: 280px; overflow-y: auto;">
${escapeHtml(c.excerpt)}
      </div>
    `;
    citationModal.classList.add('active');
  };

  closeCitationBtn?.addEventListener('click', () => citationModal.classList.remove('active'));

  // --------------------------------------------------------------------------
  // Settings Management
  // --------------------------------------------------------------------------
  async function loadSettings() {
    try {
      const s = await API.getSettings();
      activeSettings = s;
      if (providerBadge) {
        providerBadge.textContent = `${s.default_chat_provider.toUpperCase()} / ${s.default_chat_model.toUpperCase()}`;
      }
      if (providerSelect) providerSelect.value = s.default_chat_provider;
      if (modelInput) modelInput.value = s.default_chat_model;
      if (embeddingProviderSelect) embeddingProviderSelect.value = s.default_embedding_provider;
      if (embeddingModelInput) embeddingModelInput.value = s.default_embedding_model;
      if (topkSlider) topkSlider.value = s.retrieval_top_k;
      if (topkVal) topkVal.textContent = s.retrieval_top_k;
    } catch (e) {
      console.warn('Failed to load settings:', e);
    }
  }

  openSettingsBtn?.addEventListener('click', () => settingsModal?.classList.add('active'));
  closeSettingsBtn?.addEventListener('click', () => settingsModal?.classList.remove('active'));

  topkSlider?.addEventListener('input', (e) => {
    topkVal.textContent = e.target.value;
  });

  saveSettingsBtn?.addEventListener('click', async () => {
    try {
      const updated = await API.updateSettings({
        default_chat_provider: providerSelect.value,
        default_chat_model: modelInput.value.trim() || undefined,
        default_embedding_provider: embeddingProviderSelect?.value || undefined,
        default_embedding_model: embeddingModelInput?.value.trim() || undefined,
        retrieval_top_k: parseInt(topkSlider.value, 10),
      });
      activeSettings.default_chat_provider = updated.active_chat_provider;
      activeSettings.default_chat_model = updated.active_chat_model;
      activeSettings.default_embedding_provider = updated.active_embedding_provider;
      activeSettings.default_embedding_model = updated.active_embedding_model;
      activeSettings.retrieval_top_k = updated.retrieval_top_k;
      providerBadge.textContent = `${updated.active_chat_provider.toUpperCase()} / ${updated.active_chat_model}`;
      settingsModal?.classList.remove('active');
      showToast('Settings saved successfully', 'success');
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  // --------------------------------------------------------------------------
  // Form Submit & Keybindings
  // --------------------------------------------------------------------------
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
  });

  // Initial Load
  updateAuthUI();
  loadSettings();
  loadDocuments();
  loadRooms();
});
