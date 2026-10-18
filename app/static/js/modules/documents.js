/**
 * Document Ingestion, Dropzone Uploading Loader, Document Library, Audit Trail & Deletion Modal
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  let pendingDeleteDocId = null;

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

      // Auto-attach unattached documents to default room concurrently if room has no documents
      if (RAG.state.currentRoom && (!RAG.state.currentRoom.documents || RAG.state.currentRoom.documents.length === 0) && RAG.state.activeDocuments.length > 0 && !global._hasAutoAttached) {
        global._hasAutoAttached = true;
        await Promise.all(RAG.state.activeDocuments.map((d) => API.attachDocumentToRoom(RAG.state.currentRoom.id, d.id).catch(() => {})));
        const updatedRoom = await API.getRoom(RAG.state.currentRoom.id);
        RAG.state.currentRoom = updatedRoom;
        if (RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoom.id, false);
      }

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

            return `
              <div class="doc-card" id="doc-${doc.id}">
                <div class="doc-card-top">
                  <div class="doc-info" title="${RAG.utils.escapeHtml(doc.filename)}">
                    <span class="doc-icon">${icon}</span>
                    <span class="doc-name">${RAG.utils.escapeHtml(doc.filename)}</span>
                  </div>
                  <div class="doc-actions">
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

    const fileNames = Array.from(files).map((f) => f.name).join(', ');
    setDropzoneUploading(true, files.length, fileNames);
    showUploadLoaderInList(files);
    RAG.utils.showToast(`Uploading ${files.length} file(s)...`, 'info');

    try {
      if (RAG.state.currentRoomId) {
        const res = await API.uploadFilesToRoom(RAG.state.currentRoomId, files);
        RAG.utils.showToast(res.message, 'success');
      } else {
        const res = await API.uploadFiles(files);
        RAG.utils.showToast(res.message, 'success');
      }
      await loadDocuments();
      if (RAG.state.currentRoomId && RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
    } catch (e) {
      RAG.utils.showToast(e.message, 'error');
    } finally {
      setDropzoneUploading(false);
      removeUploadLoaderFromList();
      const fileInput = document.getElementById('file-input');
      if (fileInput) fileInput.value = '';
    }
  }

  function deleteDoc(docId, event) {
    if (event) {
      event.stopPropagation();
      event.preventDefault();
    }
    pendingDeleteDocId = docId;
    const doc = RAG.state.activeDocuments.find((d) => d.id === docId);
    const fname = doc ? doc.filename : 'Document';
    const ftype = doc ? doc.file_type : 'file';
    const sizeKb = doc ? Math.round(doc.file_size / 1024) : 0;
    const chunks = doc ? doc.chunk_count : 0;

    const deleteModalFilename = document.getElementById('delete-modal-filename');
    const deleteModalFileIcon = document.getElementById('delete-modal-file-icon');
    const deleteModalFilemeta = document.getElementById('delete-modal-filemeta');
    const deleteModalTitle = document.getElementById('delete-modal-title');
    const deleteModalPromptText = document.getElementById('delete-modal-prompt-text');
    const deleteModalDetachBtn = document.getElementById('delete-modal-detach-btn');
    const deleteModalConfirmBtn = document.getElementById('delete-modal-confirm-btn');
    const deleteConfirmModal = document.getElementById('delete-confirm-modal');

    if (deleteModalFilename) deleteModalFilename.textContent = fname;
    if (deleteModalFileIcon) deleteModalFileIcon.textContent = RAG.utils.iconMap[ftype] || '📄';
    if (deleteModalFilemeta) deleteModalFilemeta.textContent = `${sizeKb} KB • ${chunks} chunks`;

    if (RAG.state.currentRoomId) {
      if (deleteModalTitle) deleteModalTitle.textContent = 'Remove or Delete Document';
      if (deleteModalPromptText) {
        deleteModalPromptText.textContent =
          'This document is linked to the active workspace room. You can remove it from this room only, or permanently delete the document record.';
      }
      if (deleteModalDetachBtn) deleteModalDetachBtn.style.display = 'inline-flex';
      if (deleteModalConfirmBtn) deleteModalConfirmBtn.textContent = 'Permanently Delete';
    } else {
      if (deleteModalTitle) deleteModalTitle.textContent = 'Delete Document';
      if (deleteModalPromptText) {
        deleteModalPromptText.textContent =
          'Are you sure you want to delete this document record? Its persistent vector embeddings will remain available for shared platform RAG.';
      }
      if (deleteModalDetachBtn) deleteModalDetachBtn.style.display = 'none';
      if (deleteModalConfirmBtn) deleteModalConfirmBtn.textContent = 'Delete Document';
    }

    deleteConfirmModal?.classList.add('active');
  }

  function closeDeleteModal() {
    const deleteConfirmModal = document.getElementById('delete-confirm-modal');
    deleteConfirmModal?.classList.remove('active');
    pendingDeleteDocId = null;
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
    const closeDeleteModalBtn = document.getElementById('close-delete-modal-btn');
    const deleteModalCancelBtn = document.getElementById('delete-modal-cancel-btn');
    const deleteModalDetachBtn = document.getElementById('delete-modal-detach-btn');
    const deleteModalConfirmBtn = document.getElementById('delete-modal-confirm-btn');
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

    closeDeleteModalBtn?.addEventListener('click', closeDeleteModal);
    deleteModalCancelBtn?.addEventListener('click', closeDeleteModal);

    deleteModalDetachBtn?.addEventListener('click', async () => {
      if (!pendingDeleteDocId || !RAG.state.currentRoomId) return;
      const docId = pendingDeleteDocId;
      closeDeleteModal();
      try {
        await API.detachDocumentFromRoom(RAG.state.currentRoomId, docId);
        RAG.utils.showToast('Document removed from room workspace', 'success');
        loadDocuments();
        if (RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
      } catch (e) {
        RAG.utils.showToast(e.message, 'error');
      }
    });

    deleteModalConfirmBtn?.addEventListener('click', async () => {
      if (!pendingDeleteDocId) return;
      const docId = pendingDeleteDocId;
      closeDeleteModal();
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
    });

    const closeAuditModal = () => auditModal?.classList.remove('active');
    closeAuditModalBtn?.addEventListener('click', closeAuditModal);
    closeAuditBtn?.addEventListener('click', closeAuditModal);
  }

  RAG.documents = {
    loadDocuments,
    handleFileUpload,
    deleteDoc,
    reprocessDoc,
    showDocAudit,
    setDropzoneUploading,
    showUploadLoaderInList,
    removeUploadLoaderFromList,
    init: initDocumentListeners,
  };

  global.loadDocuments = loadDocuments;
  global.deleteDoc = deleteDoc;
  global.reprocessDoc = reprocessDoc;
  global.showDocAudit = showDocAudit;
  global.retryLoadDocs = () => loadDocuments(true);
})(window);
