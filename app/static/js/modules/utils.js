/**
 * Performance Utilities, DOM Helpers & Toast Notifications
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  // Global Shared State
  RAG.state = {
    currentRoomId: API.getActiveRoomId() || null,
    currentRoom: null,
    rooms: [],
    currentConversationId: localStorage.getItem('rag_active_conv_id') || null,
    activeDocuments: [],
    pollInterval: null,
    activeSettings: null,
    lastUserQuery: '',
  };

  // File type icons
  const iconMap = {
    pdf: '📄',
    docx: '📝',
    txt: '📃',
    md: '📑',
    csv: '📊',
    html: '🌐',
  };

  // Toast Notifications
  function showToast(message, type = 'info') {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) return;
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

  // HTML Entity Escaper
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Decode JWT payload for Inspector
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

  // RequestAnimationFrame Smooth Scrolling
  let scrollScheduled = false;
  function scheduleScrollToBottom(immediate = false) {
    const container = document.getElementById('messages-container');
    if (!container) return;
    if (immediate) {
      container.scrollTop = container.scrollHeight;
      return;
    }
    if (!scrollScheduled) {
      scrollScheduled = true;
      requestAnimationFrame(() => {
        container.scrollTop = container.scrollHeight;
        scrollScheduled = false;
      });
    }
  }

  // Mobile Navigation Drawer Helpers
  function openMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    sidebar?.classList.add('open');
    backdrop?.classList.add('active');
    document.body.classList.add('sidebar-drawer-open');
  }

  function closeMobileSidebar() {
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');
    sidebar?.classList.remove('open');
    backdrop?.classList.remove('active');
    document.body.classList.remove('sidebar-drawer-open');
  }

  // Universal Confirmation Modal State & Handlers
  let activeConfirmAction = null;
  let activeDetachAction = null;

  function showConfirmModal({
    title = 'Confirm Deletion',
    headerIcon = '🗑️',
    itemIcon = '📄',
    itemName = 'Item',
    itemMeta = '',
    prompt = 'Are you sure you want to delete this item? This action cannot be undone.',
    confirmText = 'Confirm Delete',
    confirmClass = 'btn btn-danger',
    showDetach = false,
    detachText = 'Remove from Room',
    onConfirm = null,
    onDetach = null,
  }) {
    const modal = document.getElementById('delete-confirm-modal');
    if (!modal) return;

    const titleEl = document.getElementById('delete-modal-title');
    const headerIconEl = document.getElementById('delete-modal-header-icon');
    const itemIconEl = document.getElementById('delete-modal-file-icon');
    const nameEl = document.getElementById('delete-modal-filename');
    const metaEl = document.getElementById('delete-modal-filemeta');
    const promptEl = document.getElementById('delete-modal-prompt-text');
    const confirmBtn = document.getElementById('delete-modal-confirm-btn');
    const detachBtn = document.getElementById('delete-modal-detach-btn');

    if (titleEl) titleEl.textContent = title;
    if (headerIconEl) headerIconEl.textContent = headerIcon;
    if (itemIconEl) itemIconEl.textContent = itemIcon;
    if (nameEl) nameEl.textContent = itemName;
    if (metaEl) {
      metaEl.textContent = itemMeta;
      metaEl.style.display = itemMeta ? 'block' : 'none';
    }
    if (promptEl) promptEl.textContent = prompt;

    if (confirmBtn) {
      confirmBtn.textContent = confirmText;
      confirmBtn.className = confirmClass;
    }

    if (detachBtn) {
      if (showDetach) {
        detachBtn.style.display = 'inline-flex';
        detachBtn.textContent = detachText;
      } else {
        detachBtn.style.display = 'none';
      }
    }

    activeConfirmAction = onConfirm;
    activeDetachAction = onDetach;

    // Use requestAnimationFrame / timeout to prevent any active click event from triggering backdrop dismiss
    setTimeout(() => {
      modal.classList.add('active');
    }, 10);
  }

  function closeConfirmModal() {
    const modal = document.getElementById('delete-confirm-modal');
    if (modal) {
      modal.classList.remove('active');
    }
    activeConfirmAction = null;
    activeDetachAction = null;
  }

  function initConfirmModal() {
    const closeBtn = document.getElementById('close-delete-modal-btn');
    const cancelBtn = document.getElementById('delete-modal-cancel-btn');
    const confirmBtn = document.getElementById('delete-modal-confirm-btn');
    const detachBtn = document.getElementById('delete-modal-detach-btn');

    closeBtn?.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      closeConfirmModal();
    });

    cancelBtn?.addEventListener('click', (e) => {
      e.stopPropagation();
      e.preventDefault();
      closeConfirmModal();
    });

    confirmBtn?.addEventListener('click', async (e) => {
      e.stopPropagation();
      e.preventDefault();
      const action = activeConfirmAction;
      closeConfirmModal();
      if (typeof action === 'function') {
        await action();
      }
    });

    detachBtn?.addEventListener('click', async (e) => {
      e.stopPropagation();
      e.preventDefault();
      const action = activeDetachAction;
      closeConfirmModal();
      if (typeof action === 'function') {
        await action();
      }
    });
  }

  // Register on RAG.utils
  RAG.utils = {
    iconMap,
    showToast,
    escapeHtml,
    parseJwtPayload,
    scheduleScrollToBottom,
    openMobileSidebar,
    closeMobileSidebar,
    showConfirmModal,
    closeConfirmModal,
    initConfirmModal,
  };

  // Expose globally for backward compatibility
  global.showToast = showToast;
  global.escapeHtml = escapeHtml;
  global.parseJwtPayload = parseJwtPayload;
  global.scheduleScrollToBottom = scheduleScrollToBottom;
  global.openMobileSidebar = openMobileSidebar;
  global.closeMobileSidebar = closeMobileSidebar;
  global.showConfirmModal = showConfirmModal;
  global.closeConfirmModal = closeConfirmModal;
})(window);
