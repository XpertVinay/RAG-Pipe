/**
 * Document Actions: Reprocessing, Auditing, Deletion & Sharing Toggles
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.documents = RAG.documents || {};

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
          RAG.documents.loadDocuments();
          if (RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
        } catch (e) {
          RAG.utils.showToast(e.message, 'error');
        }
      },
      onConfirm: async () => {
        try {
          await API.deleteDocument(docId);
          RAG.utils.showToast('Document deleted successfully', 'success');
          RAG.documents.loadDocuments();
          if (RAG.state.currentRoomId && RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
        } catch (e) {
          if (RAG.state.currentRoomId) {
            try {
              await API.detachDocumentFromRoom(RAG.state.currentRoomId, docId);
              RAG.utils.showToast('Document removed from room workspace (not platform owner)', 'info');
              RAG.documents.loadDocuments();
              if (RAG.rooms?.selectRoom) RAG.rooms.selectRoom(RAG.state.currentRoomId, false);
              return;
            } catch {}
          }
          RAG.utils.showToast(e.message, 'error');
        }
      },
    });
  }

  async function reprocessDoc(docId) {
    try {
      await API.reprocessDocument(docId);
      RAG.utils.showToast('Reprocessing started', 'success');
      RAG.documents.loadDocuments();
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

      const eventsHtml = data.events && data.events.length > 0
        ? data.events
            .map((ev) => {
              const time = new Date(ev.created_at).toLocaleString();
              let actionColor = '#3b82f6';
              if (ev.action.includes('delete')) actionColor = '#ef4444';
              else if (ev.action.includes('reprocess')) actionColor = '#f59e0b';
              else if (ev.action.includes('upload')) actionColor = '#10b981';

              const userWhoDid = ev.username ? `@${RAG.utils.escapeHtml(ev.username)}` : ev.user_id ? `User #${ev.user_id}` : 'System';
              const emailWhoDid = ev.user_email ? ` (${RAG.utils.escapeHtml(ev.user_email)})` : '';
              const evIp = ev.client_ip ? ` • IP: <code>${RAG.utils.escapeHtml(ev.client_ip)}</code>` : '';

              let detailsStr = '';
              if (ev.details) {
                try {
                  const parsed = typeof ev.details === 'string' ? JSON.parse(ev.details) : ev.details;
                  detailsStr = Object.entries(parsed)
                    .map(([k, v]) => `<span style="color: var(--text-muted);">${RAG.utils.escapeHtml(k)}:</span> <b>${RAG.utils.escapeHtml(String(v))}</b>`)
                    .join(' &nbsp;|&nbsp; ');
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
            })
            .join('')
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

  async function toggleDocShare(docId, makeShared) {
    try {
      await API.shareDocument(docId, makeShared);
      RAG.utils.showToast(makeShared ? 'Document made Public (accessible to all).' : 'Document made Private.', 'success');
      await RAG.documents.loadDocuments(true);
    } catch (err) {
      RAG.utils.showToast(err.message || 'Failed to update document sharing.', 'error');
    }
  }

  function initAuditModalEvents() {
    const closeAuditModalBtn = document.getElementById('close-audit-modal-btn');
    const closeAuditBtn = document.getElementById('close-audit-btn');
    const auditModal = document.getElementById('audit-modal');

    const closeAuditModal = () => auditModal?.classList.remove('active');
    closeAuditModalBtn?.addEventListener('click', closeAuditModal);
    closeAuditBtn?.addEventListener('click', closeAuditModal);
  }

  RAG.documents.deleteDoc = deleteDoc;
  RAG.documents.reprocessDoc = reprocessDoc;
  RAG.documents.showDocAudit = showDocAudit;
  RAG.documents.toggleDocShare = toggleDocShare;
  RAG.documents.initAuditModalEvents = initAuditModalEvents;
})(window);
