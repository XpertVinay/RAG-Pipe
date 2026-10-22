/**
 * Document Library Loader, Card Rendering & Real-Time SSE Event Handling
 *
 * Eliminates repetitive polling intervals by listening to Server-Sent Events (SSE).
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.documents = RAG.documents || {};

  let activeEventSource = null;

  function showLibraryLoader() {
    const docsCount = document.getElementById('docs-count');
    const docsList = document.getElementById('docs-list');
    if (docsCount) docsCount.textContent = 'Loading...';
    if (docsList) {
      docsList.innerHTML = `
        <div class="docs-loader-container" id="docs-library-loader">
          <div class="docs-loader-spinner"></div>
          <div class="docs-loader-text">Loading Document Index...</div>
          <div class="docs-skeleton-list">
            <div class="doc-skeleton-card">
              <div class="skeleton-line skeleton-header"></div>
              <div class="skeleton-line skeleton-sub"></div>
            </div>
            <div class="doc-skeleton-card">
              <div class="skeleton-line skeleton-header"></div>
              <div class="skeleton-line skeleton-sub"></div>
            </div>
            <div class="doc-skeleton-card">
              <div class="skeleton-line skeleton-header"></div>
              <div class="skeleton-line skeleton-sub"></div>
            </div>
          </div>
        </div>
      `;
    }
  }

  function updateDocumentCardInDom(data) {
    if (!data || !data.document_id) return;
    const card = document.getElementById(`doc-${data.document_id}`);
    if (!card) return;

    // 1. Update status badge
    const badge = card.querySelector('.status-badge');
    if (badge) {
      badge.className = `status-badge ${data.status}`;
      const isProcessing = data.status === 'processing' || data.status === 'queued';
      badge.innerHTML = `${isProcessing ? '<span class="status-pulse"></span>' : ''} ${data.status}`;
    }

    // 2. Update chunk count & metadata text
    const metaSpan = card.querySelector('.doc-meta > span:first-child');
    if (metaSpan && (data.chunk_count !== undefined || data.file_size !== undefined)) {
      const doc = RAG.state.activeDocuments?.find((d) => d.id === data.document_id);
      const sizeKb = Math.round((data.file_size || (doc ? doc.file_size : 0)) / 1024);
      const chunks = data.chunk_count !== undefined ? data.chunk_count : (doc ? doc.chunk_count : 0);
      const currentUser = API.getCurrentUser ? API.getCurrentUser() : null;
      const isMine = currentUser && doc && doc.user_id === currentUser.id;
      const ownerLabel = isMine ? '👤 Mine' : (doc?.uploader_username ? `👤 @${RAG.utils.escapeHtml(doc.uploader_username)}` : '🌐 Shared');
      metaSpan.textContent = `${sizeKb} KB • ${chunks} chunks • ${ownerLabel}`;
    }

    // 3. Update or remove error message
    let errorDiv = card.querySelector('.doc-error-text');
    if (data.status === 'failed' && data.error_message) {
      if (!errorDiv) {
        errorDiv = document.createElement('div');
        errorDiv.className = 'doc-error-text';
        errorDiv.style.cssText = 'margin-top: 6px; font-size: 0.7rem; color: var(--status-failed); line-height: 1.3;';
        card.appendChild(errorDiv);
      }
      errorDiv.textContent = data.error_message;
    } else if (data.status === 'completed' && errorDiv) {
      errorDiv.remove();
    }
  }

  function handleDocumentStatusEvent(data) {
    if (!data || !data.document_id) return;
    console.debug('[SSE] Received document_status event:', data);

    // Update in-memory state
    let matchedDoc = null;
    if (RAG.state.activeDocuments) {
      matchedDoc = RAG.state.activeDocuments.find((d) => d.id === data.document_id);
      if (matchedDoc) {
        matchedDoc.status = data.status;
        if (data.chunk_count !== undefined) matchedDoc.chunk_count = data.chunk_count;
        if (data.error_message !== undefined) matchedDoc.error_message = data.error_message;
      }
    }

    // If card exists in DOM, update in place without full page re-render
    const card = document.getElementById(`doc-${data.document_id}`);
    if (card) {
      updateDocumentCardInDom(data);
    } else if (data.status === 'completed' || data.status === 'processing') {
      // New file uploaded from another tab or container: reload documents once
      loadDocuments(false);
    }

    // Notify chat view to update readiness banner without polling
    if (RAG.chat?.onDocumentStatusEvent) {
      RAG.chat.onDocumentStatusEvent(data);
    }
  }

  function initDocumentEventsStream() {
    if (activeEventSource) {
      activeEventSource.close();
      activeEventSource = null;
    }
    if (typeof API.connectDocumentEventsStream === 'function') {
      activeEventSource = API.connectDocumentEventsStream(handleDocumentStatusEvent);
    }
  }

  async function loadDocuments(forceLoader = false) {
    const docsList = document.getElementById('docs-list');
    const docsCount = document.getElementById('docs-count');
    const tabDocsBadge = document.getElementById('tab-docs-badge');
    const currentUser = API.getCurrentUser ? API.getCurrentUser() : null;

    if (!currentUser) {
      RAG.state.activeDocuments = [];
      if (docsCount) docsCount.textContent = '0 files';
      if (tabDocsBadge) tabDocsBadge.textContent = '0';
      if (docsList) {
        docsList.innerHTML = `
          <div style="text-align: center; padding: 32px 14px; color: var(--text-muted); font-size: 0.82rem;">
            <div style="font-size: 2rem; margin-bottom: 8px;">🔒</div>
            <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 6px;">Sign in to view files</div>
            <div style="font-size: 0.75rem; line-height: 1.4; margin-bottom: 14px; color: var(--text-secondary);">Your uploaded documents and persistent embeddings are securely scoped to your account.</div>
            <button class="btn btn-primary" style="font-size: 0.75rem; padding: 6px 14px;" onclick="window.showAuthModal ? window.showAuthModal('signin') : (window.switchAuthTab?.('signin'), document.getElementById('auth-modal')?.classList.add('active'))">
              Sign In / Register
            </button>
          </div>
        `;
      }
      return;
    }

    // Ensure real-time SSE event stream is active
    if (!activeEventSource) {
      initDocumentEventsStream();
    }

    if (forceLoader || !docsList || !docsList.querySelector('.doc-card')) {
      showLibraryLoader();
    }

    try {
      const data = await API.getDocuments();
      RAG.state.activeDocuments = data.documents || [];

      if (docsCount) docsCount.textContent = `${RAG.state.activeDocuments.length} files`;
      if (tabDocsBadge) tabDocsBadge.textContent = `${RAG.state.activeDocuments.length}`;

      if (RAG.state.activeDocuments.length === 0) {
        if (docsList) {
          docsList.innerHTML = `
            <div style="text-align: center; padding: 28px 10px; color: var(--text-muted); font-size: 0.82rem;">
              No documents indexed yet.<br>Drag and drop files above to start.
            </div>
          `;
        }
        return;
      }

      if (docsList) {
        docsList.innerHTML = RAG.state.activeDocuments
          .map((doc) => {
            const icon = RAG.utils.iconMap[doc.file_type] || '📄';
            const sizeKb = Math.round(doc.file_size / 1024);
            const isProcessing = doc.status === 'processing' || doc.status === 'queued';
            const isMine = currentUser && doc.user_id === currentUser.id;
            const ownerLabel = isMine ? '👤 Mine' : (doc.uploader_username ? `👤 @${RAG.utils.escapeHtml(doc.uploader_username)}` : '🌐 Shared');
            const uploaderTitle = doc.uploader_email
              ? `Uploaded by ${RAG.utils.escapeHtml(doc.uploader_username || 'User')} (${RAG.utils.escapeHtml(doc.uploader_email)})`
              : (doc.uploader_username ? `Uploaded by @${RAG.utils.escapeHtml(doc.uploader_username)}` : 'Shared document');
            const persistentBadge = doc.is_persistent_vector ? `<span class="badge-pill" style="font-size: 0.65rem; background: rgba(59, 130, 246, 0.15); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3);">⚡ Persistent Vector</span>` : '';
            const privacyBadge = doc.is_shared
              ? `<span class="badge-pill" style="font-size: 0.65rem; background: rgba(16, 185, 129, 0.15); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3);" title="Public: Visible to all authorized users">🌐 Public</span>`
              : `<span class="badge-pill" style="font-size: 0.65rem; background: rgba(107, 114, 128, 0.15); color: #9ca3af; border: 1px solid rgba(107, 114, 128, 0.3);" title="Private: Visible only to you or invited room members">🔒 Private</span>`;

            const shareBtn = isMine ? `
              <button class="doc-btn" type="button" onclick="event.stopPropagation(); event.preventDefault(); window.toggleDocShare('${doc.id}', ${!doc.is_shared})" title="${doc.is_shared ? 'Make Private' : 'Make Public'}">
                ${doc.is_shared ? '🔒' : '🌐'}
              </button>
            ` : '';

            return `
              <div class="doc-card" id="doc-${doc.id}">
                <div class="doc-card-top">
                  <div class="doc-info" title="${RAG.utils.escapeHtml(doc.filename)}">
                    <span class="doc-icon">${icon}</span>
                    <span class="doc-name">${RAG.utils.escapeHtml(doc.filename)}</span>
                  </div>
                  <div class="doc-actions">
                    ${shareBtn}
                    <button class="doc-btn" type="button" onclick="event.stopPropagation(); event.preventDefault(); window.showDocAudit('${doc.id}')" title="Audit Trail & Uploader Details">📜</button>
                    <button class="doc-btn" type="button" onclick="event.stopPropagation(); event.preventDefault(); window.reprocessDoc('${doc.id}')" title="Reprocess Document">🔄</button>
                    <button class="doc-btn delete" type="button" onclick="event.stopPropagation(); event.preventDefault(); window.deleteDoc('${doc.id}', event)" title="Delete or Remove Document">🗑️</button>
                  </div>
                </div>
                <div class="doc-meta" style="flex-wrap: wrap; gap: 6px;">
                  <span title="${uploaderTitle}">${sizeKb} KB • ${doc.chunk_count} chunks • ${ownerLabel}</span>
                  <span class="status-badge ${doc.status}">
                    ${isProcessing ? '<span class="status-pulse"></span>' : ''}
                    ${doc.status}
                  </span>
                  ${privacyBadge}
                  ${persistentBadge}
                </div>
                ${doc.error_message ? `<div class="doc-error-text" style="margin-top: 6px; font-size: 0.7rem; color: var(--status-failed); line-height: 1.3;">${RAG.utils.escapeHtml(doc.error_message)}</div>` : ''}
              </div>
            `;
          })
          .join('');
      }

      // Check initial readiness status once on load without starting interval polling
      if (RAG.chat?.checkDocumentQueueReadiness) {
        RAG.chat.checkDocumentQueueReadiness(false);
      }
    } catch (e) {
      console.error('Error fetching documents:', e);
      if (docsList && !docsList.querySelector('.doc-card')) {
        docsList.innerHTML = `
          <div style="text-align: center; padding: 24px 10px; color: var(--status-failed); font-size: 0.8rem;">
            Failed to load documents.<br>
            <button class="btn btn-outline" style="margin-top: 10px; font-size: 0.75rem; padding: 4px 10px;" onclick="window.retryLoadDocs()">Retry</button>
          </div>
        `;
      }
    }
  }

  RAG.documents.showLibraryLoader = showLibraryLoader;
  RAG.documents.loadDocuments = loadDocuments;
  RAG.documents.initEventsStream = initDocumentEventsStream;
  RAG.documents.updateDocumentCardInDom = updateDocumentCardInDom;
})(window);
