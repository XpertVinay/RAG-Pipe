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

  // Register on RAG.utils
  RAG.utils = {
    iconMap,
    showToast,
    escapeHtml,
    parseJwtPayload,
    scheduleScrollToBottom,
    openMobileSidebar,
    closeMobileSidebar,
  };

  // Expose globally for backward compatibility
  global.showToast = showToast;
  global.escapeHtml = escapeHtml;
  global.parseJwtPayload = parseJwtPayload;
  global.scheduleScrollToBottom = scheduleScrollToBottom;
  global.openMobileSidebar = openMobileSidebar;
  global.closeMobileSidebar = closeMobileSidebar;
})(window);
