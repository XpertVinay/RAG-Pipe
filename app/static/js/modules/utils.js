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

  // Smart User-Aware Auto-Scroll Manager
  let isUserScrolledUp = false;
  let scrollScheduled = false;
  let scrollAttached = false;
  const SCROLL_BOTTOM_THRESHOLD = 80; // px threshold from bottom

  function isScrolledNearBottom(container, threshold = SCROLL_BOTTOM_THRESHOLD) {
    if (!container) return true;
    const distance = container.scrollHeight - container.clientHeight - container.scrollTop;
    return distance <= threshold;
  }

  function updateScrollBottomButton(show, hasNewContent = false) {
    const btn = document.getElementById('scroll-bottom-btn');
    if (!btn) return;
    if (show) {
      btn.classList.add('visible');
      const pulse = document.getElementById('scroll-bottom-pulse');
      if (pulse) pulse.style.display = hasNewContent ? 'inline-block' : 'none';
    } else {
      btn.classList.remove('visible');
      const pulse = document.getElementById('scroll-bottom-pulse');
      if (pulse) pulse.style.display = 'none';
    }
  }

  function initScrollManager() {
    const container = document.getElementById('messages-container');
    if (!container || scrollAttached) return;
    scrollAttached = true;

    // Detect user scroll position changes
    container.addEventListener('scroll', () => {
      const atBottom = isScrolledNearBottom(container);
      if (atBottom) {
        isUserScrolledUp = false;
        updateScrollBottomButton(false);
      } else {
        isUserScrolledUp = true;
        updateScrollBottomButton(true);
      }
    }, { passive: true });

    // Explicit user wheel/touch events scrolling upwards
    container.addEventListener('wheel', (e) => {
      if (e.deltaY < 0) {
        isUserScrolledUp = true;
        updateScrollBottomButton(true);
      }
    }, { passive: true });

    container.addEventListener('touchmove', () => {
      if (!isScrolledNearBottom(container)) {
        isUserScrolledUp = true;
        updateScrollBottomButton(true);
      }
    }, { passive: true });

    // Wire floating scroll to bottom button
    const scrollBottomBtn = document.getElementById('scroll-bottom-btn');
    if (scrollBottomBtn && !scrollBottomBtn._wired) {
      scrollBottomBtn._wired = true;
      scrollBottomBtn.addEventListener('click', () => {
        isUserScrolledUp = false;
        updateScrollBottomButton(false);
        if (container.scrollTo) {
          container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
        } else {
          container.scrollTop = container.scrollHeight;
        }
      });
    }
  }

  function scheduleScrollToBottom(force = false) {
    const container = document.getElementById('messages-container');
    if (!container) return;

    if (!scrollAttached) {
      initScrollManager();
    }

    if (force) {
      isUserScrolledUp = false;
      updateScrollBottomButton(false);
      container.scrollTop = container.scrollHeight;
      return;
    }

    // If the user has scrolled up to read previous or initial content, DO NOT force scroll!
    if (isUserScrolledUp) {
      updateScrollBottomButton(true, true);
      return;
    }

    if (!scrollScheduled) {
      scrollScheduled = true;
      requestAnimationFrame(() => {
        if (!isUserScrolledUp) {
          container.scrollTop = container.scrollHeight;
        }
        scrollScheduled = false;
      });
    }
  }

  function getIsUserScrolledUp() {
    return isUserScrolledUp;
  }

  function setIsUserScrolledUp(val) {
    isUserScrolledUp = Boolean(val);
    updateScrollBottomButton(isUserScrolledUp);
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
    initScrollManager,
    getIsUserScrolledUp,
    setIsUserScrolledUp,
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
  global.initScrollManager = initScrollManager;
  global.getIsUserScrolledUp = getIsUserScrolledUp;
  global.setIsUserScrolledUp = setIsUserScrolledUp;
  global.openMobileSidebar = openMobileSidebar;
  global.closeMobileSidebar = closeMobileSidebar;
  global.showConfirmModal = showConfirmModal;
  global.closeConfirmModal = closeConfirmModal;
})(window);
