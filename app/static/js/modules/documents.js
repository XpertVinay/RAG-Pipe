/**
 * Document Ingestion, Dropzone Uploading Loader, Document Library, Audit Trail & Deletion Modal
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;


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

  function setDropzoneUploading(isUploading, fileCount = 1, fileNames = '') {
    const dropzone = document.getElementById('dropzone');
    if (!dropzone) return;
    if (isUploading) {
      dropzone.classList.add('uploading');
      dropzone.innerHTML = `
        <div class="dropzone-upload-loader">
          <div class="dropzone-upload-spinner"></div>
          <div class="dropzone-upload-text">Uploading &amp; Ingesting ${fileCount} file${fileCount > 1 ? 's' : ''}...</div>
          <div class="dropzone-upload-subtext">${fileNames ? RAG.utils.escapeHtml(fileNames) : 'Parsing, chunking, and indexing embeddings...'}</div>
          <div class="dropzone-progress-bar">
            <div class="dropzone-progress-fill"></div>
          </div>
        </div>
      `;
    } else {
      dropzone.classList.remove('uploading');
      const currentUser = API.getCurrentUser();
      const hintBadge = currentUser
        ? '<span style="color: #10b981; font-weight: 500;">✓ Authenticated Uploader</span>'
        : '<span style="color: #f59e0b; font-weight: 500;">🔒 Sign in required to upload</span>';
      dropzone.innerHTML = `
        <div class="dropzone-icon">📁</div>
        <div class="dropzone-text">
          Drag &amp; drop files or <span>browse</span>
        </div>
        <div class="dropzone-hint">
          Supports PDF, DOCX, TXT, MD, CSV, HTML (Max 25MB) • ${hintBadge}
        </div>
      `;
    }
  }

  function showUploadLoaderInList(files) {
    const docsList = document.getElementById('docs-list');
    if (!docsList) return;
    const existing = document.getElementById('upload-loader-card');
    if (existing) existing.remove();

    const fileNames = Array.from(files).map((f) => f.name).join(', ');
    const loaderCard = document.createElement('div');
    loaderCard.id = 'upload-loader-card';
    loaderCard.className = 'doc-card-uploading';
    loaderCard.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <div class="docs-loader-spinner" style="width: 18px; height: 18px; border-width: 2px;"></div>
          <span style="font-weight: 600; font-size: 0.85rem; color: var(--text-primary);">
            Uploading ${files.length} document${files.length > 1 ? 's' : ''}...
          </span>
        </div>
        <span class="status-badge processing" style="font-size: 0.65rem;">
          <span class="status-pulse"></span>uploading
        </span>
      </div>
      <div style="font-size: 0.72rem; color: var(--text-secondary); text-overflow: ellipsis; overflow: hidden; white-space: nowrap;">
        ${RAG.utils.escapeHtml(fileNames)}
      </div>
      <div class="dropzone-progress-bar" style="width: 100%; margin-top: 4px;">
        <div class="dropzone-progress-fill"></div>
      </div>
    `;
    docsList.prepend(loaderCard);
  }

  function removeUploadLoaderFromList() {
    const loaderCard = document.getElementById('upload-loader-card');
    if (loaderCard) loaderCard.remove();
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
            const currentUser = API.getCurrentUser();
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

  async function handleFileUpload(files) {
    if (!files || files.length === 0) return;
    const currentUser = API.getCurrentUser();
    if (!currentUser) {
      RAG.utils.showToast('Authentication required to upload documents. Please log in or register.', 'warning');
      const authModal = document.getElementById('auth-modal');
      if (authModal) authModal.classList.add('active');
      return;
    }

    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');

    // Client-side JavaScript file validation
    let filesToUpload = files;
    if (RAG.validator) {
      const validationResult = RAG.validator.validateFiles(files);
      if (!validationResult.valid) {
        if (validationResult.rejectedFiles.length === files.length) {
          // All files rejected
          if (dropzone) {
            dropzone.classList.remove('input-shake');
            void dropzone.offsetWidth;
            dropzone.classList.add('input-shake');
            setTimeout(() => dropzone.classList.remove('input-shake'), 400);
          }
          const reasons = validationResult.rejectedFiles.map((r) => `${r.file.name}: ${r.reason}`).join(' | ');
          RAG.utils.showToast(validationResult.message || `File validation failed: ${reasons}`, 'error');
          if (fileInput) fileInput.value = '';
          return;
        } else {
          // Partial rejection: notify and upload valid files only
          const rejectedSummary = validationResult.rejectedFiles.map((r) => `${r.file.name} (${r.reason})`).join('; ');
          RAG.utils.showToast(`Skipping invalid files: ${rejectedSummary}`, 'warning');
          filesToUpload = validationResult.validFiles;
        }
      }
    }

    const fileNames = Array.from(filesToUpload).map((f) => f.name).join(', ');
    setDropzoneUploading(true, filesToUpload.length, fileNames);
    showUploadLoaderInList(filesToUpload);
    RAG.utils.showToast(`Uploading ${filesToUpload.length} file(s)...`, 'info');

    try {
      if (RAG.state.currentRoomId) {
        const res = await API.uploadFilesToRoom(RAG.state.currentRoomId, filesToUpload);
        RAG.utils.showToast(res.message, 'success');
      } else {
        const res = await API.uploadFiles(filesToUpload);
        RAG.utils.showToast(res.message, 'success');
      }
      await loadDocuments();
      if (RAG.state.currentRoomId && RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
    } catch (e) {
      RAG.utils.showToast(e.message, 'error');
    } finally {
      setDropzoneUploading(false);
      removeUploadLoaderFromList();
      if (fileInput) fileInput.value = '';
    }
  }

  function deleteDoc(docId, event) {
    if (event) {
      event.stopPropagation();
      event.preventDefault();
    }
    const doc = RAG.state.activeDocuments.find((d) => d.id === docId);
    const fname = doc ? doc.filename : 'Document';
    const ftype = doc ? doc.file_type : 'file';
    const sizeKb = doc ? Math.round(doc.file_size / 1024) : 0;
    const chunks = doc ? doc.chunk_count : 0;
    const inRoom = Boolean(RAG.state.currentRoomId);

    RAG.utils.showConfirmModal({
      title: inRoom ? 'Remove or Delete Document' : 'Delete Document',
      headerIcon: '🗑️',
      itemIcon: RAG.utils.iconMap[ftype] || '📄',
      itemName: fname,
      itemMeta: `${sizeKb} KB • ${chunks} chunks`,
      prompt: inRoom
        ? 'This document is linked to the active workspace room. You can remove it from this room only, or permanently delete the document record.'
        : 'Are you sure you want to delete this document record? Its persistent vector embeddings will remain available for shared platform RAG.',
      confirmText: inRoom ? 'Permanently Delete' : 'Delete Document',
      showDetach: inRoom,
      detachText: 'Remove from Room',
      onDetach: async () => {
        try {
          await API.detachDocumentFromRoom(RAG.state.currentRoomId, docId);
          RAG.utils.showToast('Document removed from room workspace', 'success');
          loadDocuments();
          if (RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
        } catch (e) {
          RAG.utils.showToast(e.message, 'error');
        }
      },
      onConfirm: async () => {
        try {
          await API.deleteDocument(docId);
          RAG.utils.showToast('Document deleted successfully', 'success');
          loadDocuments();
          if (RAG.state.currentRoomId && RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
        } catch (e) {
          if (RAG.state.currentRoomId) {
            try {
              await API.detachDocumentFromRoom(RAG.state.currentRoomId, docId);
              RAG.utils.showToast('Document removed from room workspace (not platform owner)', 'info');
              loadDocuments();
              if (RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
              return;
            } catch {}
          }
          RAG.utils.showToast(e.message, 'error');
        }
      },
    });
  }

  function closeDeleteModal() {
    RAG.utils?.closeConfirmModal();
  }

  async function reprocessDoc(docId) {
    try {
      await API.reprocessDocument(docId);
      RAG.utils.showToast('Reprocessing started', 'success');
      loadDocuments();
    } catch (e) {
      RAG.utils.showToast(e.message, 'error');
    }
  }

  async function showDocAudit(docId) {
    const auditModal = document.getElementById('audit-modal');
    const auditModalBody = document.getElementById('audit-modal-body');
    if (!auditModal || !auditModalBody) return;
    auditModal.classList.add('active');
    auditModalBody.innerHTML = `
      <div style="text-align: center; padding: 30px; color: var(--text-muted);">
        <div class="status-pulse" style="display: inline-block; margin-bottom: 10px;"></div>
        <div>Loading audit trail & uploader information...</div>
      </div>
    `;

    try {
      const data = await API.getDocumentAudit(docId);
      const uploader = data.uploader_username || 'Anonymous / System';
      const uploaderEmail = data.uploader_email || 'Not specified';
      const uploaderId = data.uploader_id ? `#${data.uploader_id}` : 'N/A';
      const ip = data.client_ip || 'Internal / Localhost';
      const userAgent = data.user_agent ? RAG.utils.escapeHtml(data.user_agent.substring(0, 100)) : 'Standard Client';
      const uploadTime = data.uploaded_at ? new Date(data.uploaded_at).toLocaleString() : 'N/A';

      const eventsHtml = (data.events && data.events.length > 0)
        ? data.events.map(ev => {
            const time = new Date(ev.created_at).toLocaleString();
            let actionColor = '#3b82f6';
            if (ev.action.includes('delete')) actionColor = '#ef4444';
            else if (ev.action.includes('reprocess')) actionColor = '#f59e0b';
            else if (ev.action.includes('upload')) actionColor = '#10b981';

            const userWhoDid = ev.username ? `@${RAG.utils.escapeHtml(ev.username)}` : (ev.user_id ? `User #${ev.user_id}` : 'System');
            const emailWhoDid = ev.user_email ? ` (${RAG.utils.escapeHtml(ev.user_email)})` : '';
            const evIp = ev.client_ip ? ` • IP: <code>${RAG.utils.escapeHtml(ev.client_ip)}</code>` : '';

            let detailsStr = '';
            if (ev.details) {
              try {
                const parsed = typeof ev.details === 'string' ? JSON.parse(ev.details) : ev.details;
                detailsStr = Object.entries(parsed).map(([k, v]) => `<span style="color: var(--text-muted);">${RAG.utils.escapeHtml(k)}:</span> <b>${RAG.utils.escapeHtml(String(v))}</b>`).join(' &nbsp;|&nbsp; ');
              } catch {
                detailsStr = RAG.utils.escapeHtml(String(ev.details));
              }
            }

            return `
              <div style="padding: 12px; margin-bottom: 10px; background: var(--bg-tertiary); border: 1px solid var(--border-color); border-radius: var(--radius-md); border-left: 3px solid ${actionColor}; font-size: 0.82rem;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; flex-wrap: wrap; gap: 6px;">
                  <span style="font-weight: 600; font-family: monospace; color: ${actionColor}; text-transform: uppercase;">${RAG.utils.escapeHtml(ev.action)}</span>
                  <span style="color: var(--text-muted); font-size: 0.75rem;">${time}</span>
                </div>
                <div style="color: var(--text-secondary); margin-bottom: 4px;">
                  <span>By: <b>${userWhoDid}</b>${emailWhoDid}${evIp}</span>
                </div>
                ${detailsStr ? `<div style="color: var(--text-primary); font-size: 0.78rem; background: rgba(0,0,0,0.15); padding: 6px 8px; border-radius: 4px; margin-top: 4px;">${detailsStr}</div>` : ''}
              </div>
            `;
          }).join('')
        : `<div style="text-align: center; color: var(--text-muted); padding: 20px;">No audit events recorded yet.</div>`;

      auditModalBody.innerHTML = `
        <div style="margin-bottom: 16px; padding: 14px; background: var(--bg-tertiary); border-radius: var(--radius-md); border: 1px solid var(--border-color);">
          <div style="font-size: 1rem; font-weight: 600; color: var(--text-primary); margin-bottom: 8px; word-break: break-all;">
            📄 ${RAG.utils.escapeHtml(data.filename)}
          </div>
          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 8px; font-size: 0.8rem; color: var(--text-secondary);">
            <div><b>Uploader:</b> ${RAG.utils.escapeHtml(uploader)} (ID: ${uploaderId})</div>
            <div><b>Email:</b> ${RAG.utils.escapeHtml(uploaderEmail)}</div>
            <div><b>Upload Date:</b> ${uploadTime}</div>
            <div><b>Client IP:</b> <code>${RAG.utils.escapeHtml(ip)}</code></div>
          </div>
          <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 8px; border-top: 1px dashed var(--border-color); padding-top: 6px;">
            <b>Client Agent:</b> ${userAgent}
          </div>
        </div>

        <div style="font-size: 0.85rem; font-weight: 600; margin-bottom: 10px; color: var(--text-primary); display: flex; align-items: center; justify-content: space-between;">
          <span>Security Audit Trail Log</span>
          <span class="badge-pill" style="font-size: 0.7rem; background: rgba(59, 130, 246, 0.15); color: #60a5fa;">${data.events ? data.events.length : 0} Events</span>
        </div>
        <div style="max-height: 380px; overflow-y: auto; padding-right: 4px;">
          ${eventsHtml}
        </div>
      `;
    } catch (err) {
      auditModalBody.innerHTML = `
        <div style="text-align: center; padding: 20px; color: var(--status-failed);">
          Failed to load audit trail: ${RAG.utils.escapeHtml(err.message)}
        </div>
      `;
    }
  }

  function initDocumentListeners() {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');
    const closeAuditModalBtn = document.getElementById('close-audit-modal-btn');
    const closeAuditBtn = document.getElementById('close-audit-btn');
    const auditModal = document.getElementById('audit-modal');

    dropzone?.addEventListener('click', () => {
      if (!API.getCurrentUser()) {
        RAG.utils.showToast('Authentication required to upload documents. Please log in or register.', 'warning');
        const authModal = document.getElementById('auth-modal');
        if (authModal) authModal.classList.add('active');
        return;
      }
      fileInput?.click();
    });
    fileInput?.addEventListener('change', (e) => handleFileUpload(e.target.files));

    ['dragenter', 'dragover'].forEach((ev) => {
      dropzone?.addEventListener(ev, (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
      });
    });

    ['dragleave'].forEach((ev) => {
      dropzone?.addEventListener(ev, (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
      });
    });

    dropzone?.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (!API.getCurrentUser()) {
        RAG.utils.showToast('Authentication required to upload documents. Please log in or register.', 'warning');
        const authModal = document.getElementById('auth-modal');
        if (authModal) authModal.classList.add('active');
        return;
      }
      if (e.dataTransfer.files) {
        handleFileUpload(e.dataTransfer.files);
      }
    });

    const closeAuditModal = () => auditModal?.classList.remove('active');
    closeAuditModalBtn?.addEventListener('click', closeAuditModal);
    closeAuditBtn?.addEventListener('click', closeAuditModal);
  }

  async function toggleDocShare(docId, makeShared) {
    try {
      await API.shareDocument(docId, makeShared);
      RAG.utils.showToast(makeShared ? 'Document made Public (accessible to all).' : 'Document made Private.', 'success');
      await loadDocuments(true);
    } catch (err) {
      RAG.utils.showToast(err.message || 'Failed to update document sharing.', 'error');
    }
  }

  RAG.documents = {
    loadDocuments,
    handleFileUpload,
    deleteDoc,
    reprocessDoc,
    showDocAudit,
    toggleDocShare,
    setDropzoneUploading,
    showUploadLoaderInList,
    removeUploadLoaderFromList,
    init: initDocumentListeners,
  };

  global.loadDocuments = loadDocuments;
  global.deleteDoc = deleteDoc;
  global.reprocessDoc = reprocessDoc;
  global.showDocAudit = showDocAudit;
  global.toggleDocShare = toggleDocShare;
  global.retryLoadDocs = () => loadDocuments(true);
})(window);
