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

  function renderInitialViewHtml(options = {}) {
    const { title, subtitle, authButtonsHtml, attachedDocsHtml } = options;
    return `
      <div class="welcome-screen">
        <!-- Hero / Application Objective -->
        <div class="welcome-screen-hero">
          <div class="welcome-pill-badge">
            <span>✨</span>
            <span>Enterprise RAG &amp; Grounded Multi-Tenant Intelligence</span>
          </div>
          <h3 id="welcome-title">${title || 'RAG Agent — Verifiable Document Intelligence'}</h3>
          <p class="welcome-lead">
            ${subtitle || 'Ingest, index, and query complex enterprise files (PDF, DOCX, CSV, TXT, Markdown, and Code) with zero hallucinations. Powered by stateful LangGraph agent orchestration, hybrid vector retrieval, and verifiable citations pinned to source database chunks.'}
          </p>
          ${authButtonsHtml || ''}

          <!-- Objective Feature Matrix -->
          <div class="objective-matrix">
            <div class="objective-item">
              <span class="objective-icon">🎯</span>
              <h4>Zero Hallucinations</h4>
              <p>Strictly grounded in validated document chunks with verifiable citation badges.</p>
            </div>
            <div class="objective-item">
              <span class="objective-icon">⚡</span>
              <h4>LangGraph Agent</h4>
              <p>Stateful multi-turn reasoning, dynamic query decomposition, and autonomous tools.</p>
            </div>
            <div class="objective-item">
              <span class="objective-icon">🏢</span>
              <h4>Isolated Workspaces</h4>
              <p>Role-based access control (RBAC), room multi-tenancy, and persistent context.</p>
            </div>
            <div class="objective-item">
              <span class="objective-icon">🔒</span>
              <h4>Enterprise Privacy</h4>
              <p>AES-256 encrypted vector embeddings at rest and TLS 1.3 streaming security.</p>
            </div>
          </div>
        </div>

        <!-- Attached & Recent Documents Showcase for Active Grounded Chat -->
        ${attachedDocsHtml || ''}

        <!-- Curated Industry Intelligence & Top News Header -->
        <div class="intel-news-header">
          <div class="intel-news-header-left">
            <span>📰</span>
            <h4>Industry Briefing: AI Breakthroughs, PropTech Markets &amp; Security Defense</h4>
          </div>
          <div class="intel-live-indicator">
            <span>Live Briefing Feed</span>
          </div>
        </div>

        <!-- 3-Column News & Intelligence Grid -->
        <div class="intel-cards-grid">
          <!-- Card 1: AI (Artificial Intelligence) -->
          <div class="intel-card card-ai">
            <span class="intel-card-badge badge-ai">🤖 AI &amp; Autonomous Agents</span>
            <h5 class="intel-card-title">Autonomous Agentic RAG &amp; Reasoning Models</h5>
            <p class="intel-card-headline">
              Enterprise workflows are transitioning from static vector similarity searches to multi-agent LangGraph architectures that autonomously verify citations and self-correct.
            </p>
            <div class="intel-news-item">
              <strong>Multimodal Ingestion:</strong> Frontier reasoning models extract tables, balance sheets, and schematics directly from scanned documents with high layout fidelity.
            </div>
            <div class="intel-news-item">
              <strong>Hallucination Defense:</strong> Recursive citation cross-referencing reduces factual drift to under 2% across enterprise benchmarks.
            </div>
            <div class="intel-card-action">
              <button class="intel-prompt-btn" type="button" onclick="window.usePrompt('Explain how autonomous agentic RAG and LangGraph workflows eliminate hallucinations compared to standard vector search.')">
                <span>Ask: "How does agentic RAG eliminate hallucinations?"</span>
                <span class="arrow">➤</span>
              </button>
            </div>
          </div>

          <!-- Card 2: Real Estate & PropTech -->
          <div class="intel-card card-realestate">
            <span class="intel-card-badge badge-realestate">🏙️ Real Estate &amp; PropTech</span>
            <h5 class="intel-card-title">Predictive Underwriting &amp; Automated Lease Audits</h5>
            <p class="intel-card-headline">
              Commercial real estate firms are accelerating deal velocity by using AI agents to parse 200+ page lease agreements, rent rolls, and zoning covenants in seconds.
            </p>
            <div class="intel-news-item">
              <strong>Automated Valuation:</strong> Spatial telemetry and predictive underwriting models streamline title review and cap-rate sensitivity stress testing.
            </div>
            <div class="intel-news-item">
              <strong>ESG &amp; Carbon Audits:</strong> Institutional landlords deploy IoT telemetry agents to satisfy mandatory corporate climate disclosures and building energy ratings.
            </div>
            <div class="intel-card-action">
              <button class="intel-prompt-btn" type="button" onclick="window.usePrompt('What are the key legal, financial, and environmental risks to audit in commercial real estate lease agreements?')">
                <span>Ask: "Audit commercial real estate lease risks"</span>
                <span class="arrow">➤</span>
              </button>
            </div>
          </div>

          <!-- Card 3: Security & How to Become Safe and Secure -->
          <div class="intel-card card-security">
            <span class="intel-card-badge badge-security">🛡️ Security &amp; Defense</span>
            <h5 class="intel-card-title">Securing Vector Stores &amp; Prompt Injections</h5>
            <p class="intel-card-headline">
              OWASP Top 10 for LLMs identifies indirect prompt injection, vector data poisoning, and unauthorized retrieval leakage as paramount threats to enterprise generative AI.
            </p>

            <!-- How to Become Safe and Secure Actionable Guide -->
            <div class="security-guide-box">
              <div class="security-guide-title">
                <span>🔒</span>
                <span>How to Become Safe &amp; Secure</span>
              </div>
              <ul class="security-steps-list">
                <li>
                  <span class="security-step-bullet">1.</span>
                  <span><strong>Passkeys &amp; MFA:</strong> Mandate hardware FIDO2 or authenticator apps; eliminate SMS OTPs to block credential phishing.</span>
                </li>
                <li>
                  <span class="security-step-bullet">2.</span>
                  <span><strong>Zero-Trust &amp; RBAC:</strong> Segment workspace rooms so sensitive documents are never indexed into general pools.</span>
                </li>
                <li>
                  <span class="security-step-bullet">3.</span>
                  <span><strong>Encryption at Rest &amp; Transit:</strong> Enforce AES-256 for vector embeddings and TLS 1.3 for all streaming SSE channels.</span>
                </li>
                <li>
                  <span class="security-step-bullet">4.</span>
                  <span><strong>Prompt Injection Guardrails:</strong> Sanitize all retrieval inputs and scrub PII or secrets before LLM synthesis.</span>
                </li>
                <li>
                  <span class="security-step-bullet">5.</span>
                  <span><strong>Immutable Backups &amp; Audit Logs:</strong> Maintain tamper-proof revision trails and rotate API keys regularly.</span>
                </li>
              </ul>
            </div>

            <div class="intel-card-action">
              <button class="intel-prompt-btn" type="button" onclick="window.usePrompt('Provide an actionable enterprise security checklist to safeguard our RAG pipelines against prompt injections and data leaks.')">
                <span>Ask: "Security checklist for safe RAG pipelines"</span>
                <span class="arrow">➤</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Quick Action Prompts Tray -->
        <div class="quick-prompts">
          <div style="font-size: 0.76rem; color: var(--text-muted); margin-bottom: 4px;">
            ⚡ Quick Starters — Click any prompt to query active room documents:
          </div>
          <div class="quick-prompts-tray">
            <button class="quick-prompt-btn" type="button" onclick="window.usePrompt('Summarize the key concepts and points from the uploaded documents in this room.')">
              <span>✨</span>
              <span>"Summarize key concepts from active documents"</span>
            </button>
            <button class="quick-prompt-btn" type="button" onclick="window.usePrompt('What are the main topics and important references covered in these files?')">
              <span>🔍</span>
              <span>"Identify main topics and key database references"</span>
            </button>
            <button class="quick-prompt-btn" type="button" onclick="window.usePrompt('What security controls and compliance practices are required to protect our enterprise data?')">
              <span>🛡️</span>
              <span>"Audit data security &amp; zero-trust guidelines"</span>
            </button>
          </div>
        </div>
      </div>
    `;
  }

  function renderAttachedDocumentsHtml(docs) {
    if (!docs || docs.length === 0) {
      return `
        <div class="welcome-docs-section" style="margin: 18px 0; background: var(--bg-tertiary); border: 1px dashed var(--border-color); border-radius: var(--radius-md); padding: 14px 18px; text-align: center;">
          <div style="font-size: 1.4rem; margin-bottom: 4px;">📎</div>
          <div style="font-weight: 600; font-size: 0.82rem; color: var(--text-primary); margin-bottom: 4px;">No Documents Attached Yet</div>
          <div style="font-size: 0.74rem; color: var(--text-secondary); margin-bottom: 10px;">
            Upload files in the sidebar or click below to attach files for grounded answers with verified citations.
          </div>
          <button class="btn btn-outline" style="font-size: 0.72rem; padding: 4px 12px;" onclick="document.getElementById('file-input')?.click()">
            + Upload / Attach File
          </button>
        </div>
      `;
    }

    const pills = docs.map((doc) => {
      const icon = RAG.utils.iconMap[doc.file_type] || '📄';
      const sizeKb = Math.round((doc.file_size || 0) / 1024);
      const sizeStr = sizeKb > 1024 ? `${(sizeKb / 1024).toFixed(1)} MB` : `${sizeKb} KB`;
      const status = doc.status || 'completed';
      const isPending = status === 'queued' || status === 'processing';
      const isFailed = status === 'failed';
      let statusBadge = `<span class="status-badge completed" style="font-size: 0.65rem;">ready</span>`;
      if (isPending) {
        statusBadge = `<span class="status-badge ${status}" style="font-size: 0.65rem;"><span class="status-pulse"></span>${status}</span>`;
      } else if (isFailed) {
        statusBadge = `<span class="status-badge failed" style="font-size: 0.65rem;">failed</span>`;
      }
      const chunkLabel = isPending ? 'Processing chunks...' : `${doc.chunk_count || 0} chunks`;

      return `
        <div class="welcome-doc-pill" id="welcome-doc-${doc.id}" style="display: flex; align-items: center; justify-content: space-between; gap: 10px; background: var(--bg-secondary); border: 1px solid var(--border-color); border-radius: var(--radius-sm); padding: 8px 12px; margin-bottom: 6px;">
          <div style="display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1;">
            <span style="font-size: 1.1rem;">${icon}</span>
            <div style="min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              <div style="font-weight: 500; font-size: 0.8rem; color: var(--text-primary); text-overflow: ellipsis; overflow: hidden;" title="${RAG.utils.escapeHtml(doc.filename)}">
                ${RAG.utils.escapeHtml(doc.filename)}
              </div>
              <div style="font-size: 0.7rem; color: var(--text-secondary);">
                ${sizeStr} • ${chunkLabel}
              </div>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 6px;">
            ${statusBadge}
            <button class="btn btn-outline" type="button" style="font-size: 0.68rem; padding: 2px 8px;" onclick="window.usePrompt('Summarize key points, facts, and actionable findings from ${RAG.utils.escapeHtml(doc.filename)}')">
              Ask
            </button>
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="welcome-docs-section" style="margin: 16px 0; background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--radius-md); padding: 12px 14px;">
        <div class="welcome-docs-header" style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
          <div style="display: flex; align-items: center; gap: 6px;">
            <span>📎</span>
            <span style="font-weight: 600; font-size: 0.8rem; color: var(--text-primary);">Attached &amp; Recent Documents (${docs.length})</span>
          </div>
          <button class="btn btn-outline" type="button" style="font-size: 0.7rem; padding: 2px 8px;" onclick="document.getElementById('file-input')?.click()">
            + Add Files
          </button>
        </div>
        <div class="welcome-docs-list" style="max-height: 190px; overflow-y: auto;">
          ${pills}
        </div>
      </div>
    `;
  }

  function updateRoomFilesAndRecentDocs() {
    const bannerRoomFiles = document.getElementById('banner-room-files');
    const roomDocs = RAG.state.currentRoom?.documents || [];
    const activeDocs = RAG.state.activeDocuments || [];
    const docsToShow = roomDocs.length > 0 ? roomDocs : activeDocs;

    if (bannerRoomFiles) {
      if (docsToShow.length === 0) {
        bannerRoomFiles.innerHTML = `<span class="room-files-empty-pill"><span>📎</span><span>No files attached</span></span>`;
      } else {
        bannerRoomFiles.innerHTML = docsToShow
          .map((d) => {
            const isPending = d.status === 'queued' || d.status === 'processing';
            const icon = RAG.utils.iconMap[d.file_type] || '📄';
            const pulse = isPending
              ? '<span class="status-pulse" style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#f59e0b;margin-right:4px;"></span>'
              : '';
            const detachAction = RAG.state.currentRoom?.id
              ? `<span style="opacity: 0.6; cursor: pointer; margin-left: 4px;" onclick="window.detachDocFromRoom('${RAG.state.currentRoom.id}', '${d.id}', event)" title="Detach file from room">×</span>`
              : '';
            return `
              <span class="room-file-pill" title="${RAG.utils.escapeHtml(d.filename)} (${d.chunk_count || 0} chunks, ${d.status || 'ready'})">
                <span>${icon}</span>
                ${pulse}
                <span>${RAG.utils.escapeHtml(d.filename)}</span>
                ${detachAction}
              </span>
            `;
          })
          .join('');
      }
    }

    // Refresh welcome screen attached documents if welcome screen is active
    const welcomeDocsContainer = document.querySelector('.welcome-docs-section');
    if (welcomeDocsContainer) {
      welcomeDocsContainer.outerHTML = renderAttachedDocumentsHtml(docsToShow);
    }
  }

  function showWelcomeScreen() {
    const messagesContainer = document.getElementById('messages-container');
    if (!messagesContainer) return;
    const currentUser = API.getCurrentUser();

    if (!currentUser) {
      const authButtonsHtml = `
        <div style="margin-top: 12px; margin-bottom: 22px; display: flex; gap: 10px; justify-content: center; flex-wrap: wrap;">
          <button class="btn btn-primary" onclick="window.showAuthModal ? window.showAuthModal('signin') : (window.switchAuthTab?.('signin'), document.getElementById('auth-modal')?.classList.add('active'))">
            Sign In / Register
          </button>
          <button class="btn btn-outline" id="welcome-demo-login-btn" onclick="document.getElementById('demo-login-btn')?.click()">
            ⚡ Demo Account
          </button>
        </div>
      `;
      messagesContainer.innerHTML = renderInitialViewHtml({
        title: 'RAG Agent — Verifiable Document Intelligence',
        subtitle: 'Sign in or register to create workspaces, upload multi-format documents, and ask grounded questions with verifiable citations.',
        authButtonsHtml,
      });
      return;
    }

    const roomDocs = RAG.state.currentRoom?.documents || [];
    const activeDocs = RAG.state.activeDocuments || [];
    const docsToShow = roomDocs.length > 0 ? roomDocs : activeDocs;
    const fileCount = docsToShow.length;
    const roomTitle = RAG.state.currentRoom?.name || 'Workspace';

    messagesContainer.innerHTML = renderInitialViewHtml({
      title: `${RAG.utils.escapeHtml(roomTitle)} — Grounded AI Assistant`,
      subtitle: fileCount > 0
        ? `Ready to answer questions grounded in <strong>${fileCount} indexed file(s)</strong>. Real-time chunking and citations active.`
        : `Upload or attach documents to this workspace to begin grounded Q&amp;A with verifiable citations.`,
      attachedDocsHtml: renderAttachedDocumentsHtml(docsToShow),
    });

    updateRoomFilesAndRecentDocs();
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
      updateRoomFilesAndRecentDocs();
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

    RAG.utils?.setIsUserScrolledUp?.(false);
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
        <div class="message-bubble streaming-bubble">
          <div class="bubble-markdown streaming-markdown"></div>
          <span class="streaming-cursor"></span>
        </div>
      </div>
    `;
    messagesContainer.appendChild(assistantRow);
    RAG.utils.scheduleScrollToBottom(true);

    const avatarEl = assistantRow.querySelector('.message-avatar');
    const statusEl = assistantRow.querySelector('.status-text');
    const bubbleMarkdown = assistantRow.querySelector('.bubble-markdown');
    const streamingCursor = assistantRow.querySelector('.streaming-cursor');

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
        } else if (meta.response_type === 'queue_pending') {
          avatarEl.textContent = '⏳';
          avatarEl.className = 'message-avatar queue_pending';
        }
      },
      onToken: (tok) => {
        accumulatedContent += tok;
        if (RAG.markdown?.renderStreaming) {
          RAG.markdown.renderStreaming(bubbleMarkdown, accumulatedContent, {
            isStreaming: true,
            citations: currentCitations,
          });
        } else {
          bubbleMarkdown.textContent = accumulatedContent;
        }
        RAG.utils.scheduleScrollToBottom();
      },
      onCitations: (citations) => {
        currentCitations = citations || [];
      },
      onVisualization: (vis) => {
        receivedMeta.visualization = vis;
      },
      onDone: (data) => {
        if (sendBtn) sendBtn.disabled = false;
        chatInput.focus();

        const finalCitations = (data && data.citations) || currentCitations;
        const finalMeta = Object.assign({}, receivedMeta, data || {});

        const wasScrolledUp = RAG.utils?.getIsUserScrolledUp?.() || false;
        const prevScrollTop = messagesContainer ? messagesContainer.scrollTop : 0;

        if (streamingCursor) streamingCursor.remove();

        if (RAG.markdown?.finalizeStreaming) {
          RAG.markdown.finalizeStreaming(assistantRow, {
            content: accumulatedContent || data?.answer || '',
            citations: finalCitations,
            meta: finalMeta,
            timestamp: new Date().toISOString(),
          });
        } else {
          assistantRow.remove();
          if (RAG.markdown?.renderAssistantMessage) {
            RAG.markdown.renderAssistantMessage({
              content: accumulatedContent || data?.answer || '',
              citations: finalCitations,
              meta: finalMeta,
              timestamp: new Date().toISOString(),
            });
          }
        }

        // If the user was reading initial/earlier content, preserve their exact scroll position
        if (wasScrolledUp && messagesContainer) {
          messagesContainer.scrollTop = prevScrollTop;
        }

        if (finalMeta.guardrail_alert || finalMeta.guardrail_blocked) {
          RAG.utils.showToast(
            finalMeta.guardrail_alert || '⚠️ Safety Guardrail: Prohibited query blocked. Repeated violations will restrict your access and be reported to authorities.',
            'error',
            10000
          );
        }

        if (finalMeta.pii_breach_alert) {
          RAG.utils.showToast(finalMeta.pii_breach_alert, 'warning', 8000);
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
    const codeEl = container.querySelector('.browser-code-viewport code') || container.querySelector('pre code') || container.querySelector('code');
    if (!codeEl) return;
    let codeText = codeEl.innerText || codeEl.textContent || '';

    // If it's a terminal block, strip the leading '$ ' prompt on commands for clean execution
    if (container.classList.contains('terminal-block-container')) {
      codeText = codeText
        .split('\n')
        .map((line) => line.replace(/^\$\s+/, ''))
        .join('\n');
    }

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
    RAG.utils?.initScrollManager?.();

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

    // Wire document queue banner refresh button
    const queueRefreshBtn = document.getElementById('doc-queue-refresh-btn');
    queueRefreshBtn?.addEventListener('click', () => {
      checkDocumentQueueReadiness(true);
    });
  }

  let wasPreviouslyPending = false;

  function onDocumentStatusEvent(event) {
    const queueBanner = document.getElementById('doc-queue-banner');
    const titleText = document.getElementById('doc-queue-title-text');
    const detailText = document.getElementById('doc-queue-status-detail');
    const chatInput = document.getElementById('chat-input');
    if (!queueBanner) return;

    const fname = event.filename || 'Document';

    if (event.status === 'queued' || event.status === 'processing') {
      wasPreviouslyPending = true;
      queueBanner.style.display = 'block';
      queueBanner.classList.remove('ready');
      if (titleText) {
        titleText.textContent = event.status === 'processing'
          ? `⚙️ Indexing "${fname}" in background...`
          : `⏳ "${fname}" queued for processing...`;
      }
      if (detailText) {
        detailText.textContent = 'Worker is parsing text chunks and embedding vectors into the database.';
      }
    } else if (event.status === 'completed') {
      queueBanner.style.display = 'block';
      queueBanner.classList.add('ready');
      if (titleText) {
        titleText.textContent = `✨ "${fname}" is ready for LLM prompts!`;
      }
      if (detailText) {
        detailText.textContent = `Indexed ${event.chunk_count || 0} chunks into persistent vector store.`;
      }
      if (RAG.utils?.showToast) {
        RAG.utils.showToast(`✨ "${fname}" indexed successfully (${event.chunk_count || 0} chunks)!`, 'success');
      }
      if (chatInput) {
        chatInput.focus();
      }
      setTimeout(() => {
        if (queueBanner && queueBanner.classList.contains('ready')) {
          queueBanner.style.display = 'none';
        }
      }, 6000);
    } else if (event.status === 'failed') {
      queueBanner.style.display = 'block';
      queueBanner.classList.remove('ready');
      if (titleText) {
        titleText.textContent = `⚠️ "${fname}" failed indexing`;
      }
      if (detailText) {
        detailText.textContent = event.error_message || 'Indexing failed or worker timed out. Click Reprocess to retry.';
      }
      if (RAG.utils?.showToast) {
        RAG.utils.showToast(`⚠️ Indexing failed for ${fname}: ${event.error_message || 'Error'}`, 'error');
      }
    }

    // Live update document state in memory and refresh UI pills & welcome cards
    if (RAG.state?.activeDocuments && event.document_id) {
      const match = RAG.state.activeDocuments.find((d) => d.id === event.document_id);
      if (match) {
        match.status = event.status;
        if (event.chunk_count !== undefined) match.chunk_count = event.chunk_count;
        if (event.error_message !== undefined) match.error_message = event.error_message;
      }
    }
    if (RAG.state?.currentRoom?.documents && event.document_id) {
      const match = RAG.state.currentRoom.documents.find((d) => d.id === event.document_id);
      if (match) {
        match.status = event.status;
        if (event.chunk_count !== undefined) match.chunk_count = event.chunk_count;
        if (event.error_message !== undefined) match.error_message = event.error_message;
      }
    }
    updateRoomFilesAndRecentDocs();
  }

  async function checkDocumentQueueReadiness(forceToast = false) {
    const queueBanner = document.getElementById('doc-queue-banner');
    const titleText = document.getElementById('doc-queue-title-text');
    const detailText = document.getElementById('doc-queue-status-detail');
    const chatInput = document.getElementById('chat-input');

    const currentUser = API.getCurrentUser ? API.getCurrentUser() : null;
    if (!currentUser) {
      if (queueBanner) queueBanner.style.display = 'none';
      return;
    }

    try {
      const roomDocIds = RAG.state?.currentRoom?.documents?.map((d) => d.id) || null;
      if (typeof API.checkDocumentsReadiness !== 'function') return;

      const res = await API.checkDocumentsReadiness(RAG.state?.currentRoomId, roomDocIds);
      if (!queueBanner) return;

      if (res && res.pending_count > 0) {
        wasPreviouslyPending = true;
        queueBanner.style.display = 'block';
        queueBanner.classList.remove('ready');
        if (titleText) {
          titleText.textContent = `${res.pending_count} file(s) processing in worker queue...`;
        }
        if (detailText) {
          detailText.textContent = `Worker is parsing & indexing chunks (${res.ready_count}/${res.total} ready). Real-time updates active via SSE.`;
        }
        if (forceToast && RAG.utils?.showToast) {
          RAG.utils.showToast(`${res.pending_count} document(s) currently being indexed by background worker.`, 'info');
        }
      } else if (res && res.total > 0 && res.all_ready && wasPreviouslyPending) {
        wasPreviouslyPending = false;
        queueBanner.style.display = 'block';
        queueBanner.classList.add('ready');
        if (titleText) {
          titleText.textContent = `✨ All ${res.total} document(s) are ready for LLM prompts!`;
        }
        if (detailText) {
          detailText.textContent = 'Document chunks & vectors are persistent in vector store. You can now prompt the LLM.';
        }
        if (RAG.utils?.showToast) {
          RAG.utils.showToast(`✨ Documents ready! You can now ask questions about your documents.`, 'success');
        }
        if (chatInput) {
          chatInput.focus();
        }
        setTimeout(() => {
          if (!wasPreviouslyPending && queueBanner) {
            queueBanner.style.display = 'none';
          }
        }, 6000);
      } else if (res && res.failed_count > 0 && wasPreviouslyPending) {
        wasPreviouslyPending = false;
        queueBanner.style.display = 'block';
        queueBanner.classList.remove('ready');
        if (titleText) {
          titleText.textContent = `⚠️ ${res.failed_count} document(s) failed indexing`;
        }
        if (detailText) {
          detailText.textContent = 'Some documents encountered processing errors. Please check Document Manager to reprocess.';
        }
        if (RAG.utils?.showToast) {
          RAG.utils.showToast(`${res.failed_count} document(s) failed indexing.`, 'error');
        }
      } else {
        queueBanner.style.display = 'none';
        wasPreviouslyPending = false;
      }
    } catch (err) {
      console.warn('Error checking document readiness:', err);
    }
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
    checkDocumentQueueReadiness,
    onDocumentStatusEvent,
    updateRoomFilesAndRecentDocs,
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
  global.checkDocumentQueueReadiness = checkDocumentQueueReadiness;
})(window);
