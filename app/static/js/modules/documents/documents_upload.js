/**
 * Document Drag-and-Drop, Upload Progress Loaders & Validation Handlers
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.documents = RAG.documents || {};

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

    let filesToUpload = files;
    if (RAG.validator) {
      const validationResult = RAG.validator.validateFiles(files);
      if (!validationResult.valid) {
        if (validationResult.rejectedFiles.length === files.length) {
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
          const rejectedSummary = validationResult.rejectedFiles.map((r) => `${r.file.name} (${r.reason})`).join('; ');
          RAG.utils.showToast(`Skipping invalid files: ${rejectedSummary}`, 'warning');
          filesToUpload = validationResult.validFiles;
        }
      }
    }

    // Check if any selected files are currently actively processing in background
    if (RAG.state.activeDocuments && RAG.state.activeDocuments.length > 0) {
      const activePending = RAG.state.activeDocuments.filter((d) => d.status === 'processing' || d.status === 'queued');
      for (const f of filesToUpload) {
        const match = activePending.find((d) => d.filename === f.name || (d.file_size === f.size && d.filename.startsWith(f.name.split('.')[0])));
        if (match) {
          RAG.utils.showToast(`File "${f.name}" is already actively indexing in the background. Monitoring progress.`, 'info');
        }
      }
    }

    const fileNames = Array.from(filesToUpload).map((f) => f.name).join(', ');
    setDropzoneUploading(true, filesToUpload.length, fileNames);
    showUploadLoaderInList(filesToUpload);
    RAG.utils.showToast(`Uploading ${filesToUpload.length} file(s)...`, 'info');

    try {
      let res;
      if (RAG.state.currentRoomId) {
        res = await API.uploadFilesToRoom(RAG.state.currentRoomId, filesToUpload);
      } else {
        res = await API.uploadFiles(filesToUpload);
      }

      const toastType = res.message && (res.message.includes('skipped') || res.message.includes('already')) ? 'info' : 'success';
      RAG.utils.showToast(res.message, toastType);

      await RAG.documents.loadDocuments();
      if (RAG.state.currentRoomId && RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
      if (RAG.chat?.checkDocumentQueueReadiness) {
        RAG.chat.checkDocumentQueueReadiness(true);
      }
    } catch (e) {
      RAG.utils.showToast(e.message, 'error');
    } finally {
      setDropzoneUploading(false);
      removeUploadLoaderFromList();
      if (fileInput) fileInput.value = '';
    }
  }

  function initDropzoneEvents() {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file-input');

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
  }

  RAG.documents.setDropzoneUploading = setDropzoneUploading;
  RAG.documents.showUploadLoaderInList = showUploadLoaderInList;
  RAG.documents.removeUploadLoaderFromList = removeUploadLoaderFromList;
  RAG.documents.handleFileUpload = handleFileUpload;
  RAG.documents.initDropzoneEvents = initDropzoneEvents;
})(window);
