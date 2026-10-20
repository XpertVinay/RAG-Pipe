/**
 * Document Library Loader, Card Rendering & Status Polling
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.documents = RAG.documents || {};

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

  async function loadDocuments(forceLoader = false) {
    const docsList = document.getElementById('docs-list');
    const docsCount = document.getElementById('docs-count');
    const tabDocsBadge = document.getElementById('tab-docs-badge');
    const currentUser = API.getCurrentUser();

    if (!currentUser) {
      RAG.state.activeDocuments = [];
      if (docsCount) docsCount.textContent = '0 files';
      if (tabDocsBadge) tabDocsBadge.textContent = '0';
      if (RAG.state.pollInterval) {
        clearInterval(RAG.state.pollInterval);
        RAG.state.pollInterval = null;
      }
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

    if (forceLoader || (docsList && !docsList.querySelector('.doc-card') && !docsList.querySelector('.doc-card-uploading'))) {
      showLibraryLoader();
    }
    try {
      const data = await API.getDocuments();
      RAG.state.activeDocuments = data.items || [];
      if (docsCount) docsCount.textContent = `${RAG.state.activeDocuments.length} files`;
      if (tabDocsBadge) tabDocsBadge.textContent = RAG.state.activeDocuments.length;

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
                ${doc.error_message ? `<div style="margin-top: 6px; font-size: 0.7rem; color: var(--status-failed); line-height: 1.3;">${RAG.utils.escapeHtml(doc.error_message)}</div>` : ''}
              </div>
            `;
          })
          .join('');
      }

      const hasPending = RAG.state.activeDocuments.some((d) => d.status === 'processing' || d.status === 'queued');
      if (hasPending && !RAG.state.pollInterval) {
        RAG.state.pollInterval = setInterval(loadDocuments, 2500);
      } else if (!hasPending && RAG.state.pollInterval) {
        clearInterval(RAG.state.pollInterval);
        RAG.state.pollInterval = null;
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
})(window);
