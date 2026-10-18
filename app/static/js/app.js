/**
 * Production RAG Agent UI Master Orchestrator
 * High Performance Modular Architecture
 */
document.addEventListener('DOMContentLoaded', () => {
  'use strict';

  const RAG = window.RAG || {};

  // Sidebar Tabs Navigation
  const tabBtnRooms = document.getElementById('tab-btn-rooms');
  const tabBtnDocs = document.getElementById('tab-btn-docs');
  const tabBtnHistory = document.getElementById('tab-btn-history');
  const tabBtnMemory = document.getElementById('tab-btn-memory');
  const panelRooms = document.getElementById('panel-rooms');
  const panelDocs = document.getElementById('panel-docs');
  const panelHistory = document.getElementById('panel-history');
  const panelMemory = document.getElementById('panel-memory');
  const mobileSidebarToggle = document.getElementById('mobile-sidebar-toggle');
  const sidebarCloseBtn = document.getElementById('sidebar-close-btn');
  const sidebarBackdrop = document.getElementById('sidebar-backdrop');
  const tabMemoryBadge = document.getElementById('tab-memory-badge');

  function switchSidebarTab(tabName) {
    [tabBtnRooms, tabBtnDocs, tabBtnHistory, tabBtnMemory].forEach((b) => b?.classList.remove('active'));
    [panelRooms, panelDocs, panelHistory, panelMemory].forEach((p) => p?.classList.remove('active'));

    if (tabName === 'rooms') {
      tabBtnRooms?.classList.add('active');
      panelRooms?.classList.add('active');
      if (RAG.rooms?.loadRooms) RAG.rooms.loadRooms();
    } else if (tabName === 'docs') {
      tabBtnDocs?.classList.add('active');
      panelDocs?.classList.add('active');
      if (RAG.documents?.loadDocuments) RAG.documents.loadDocuments();
    } else if (tabName === 'memory') {
      tabBtnMemory?.classList.add('active');
      panelMemory?.classList.add('active');
      if (RAG.memory?.loadMemoryDashboard) RAG.memory.loadMemoryDashboard();
    } else {
      tabBtnHistory?.classList.add('active');
      panelHistory?.classList.add('active');
      if (RAG.history?.loadConversations) RAG.history.loadConversations();
    }
  }

  tabBtnRooms?.addEventListener('click', () => switchSidebarTab('rooms'));
  tabBtnDocs?.addEventListener('click', () => switchSidebarTab('docs'));
  tabBtnHistory?.addEventListener('click', () => switchSidebarTab('history'));
  tabBtnMemory?.addEventListener('click', () => switchSidebarTab('memory'));

  // Mobile Drawer Navigation
  mobileSidebarToggle?.addEventListener('click', RAG.utils?.openMobileSidebar);
  sidebarCloseBtn?.addEventListener('click', RAG.utils?.closeMobileSidebar);
  sidebarBackdrop?.addEventListener('click', RAG.utils?.closeMobileSidebar);

  // Universal Modal Backdrop Click & Escape Key Dismissal
  const allModals = [
    document.getElementById('auth-modal'),
    document.getElementById('room-modal'),
    document.getElementById('settings-modal'),
    document.getElementById('citation-modal'),
    document.getElementById('memory-modal'),
    document.getElementById('delete-confirm-modal'),
    document.getElementById('audit-modal'),
  ].filter(Boolean);

  allModals.forEach((modal) => {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.classList.remove('active');
        modal.classList.remove('open');
      }
    });
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      allModals.forEach((modal) => {
        modal?.classList.remove('active');
        modal?.classList.remove('open');
      });
      if (RAG.utils?.closeMobileSidebar) RAG.utils.closeMobileSidebar();
    }
  });

  async function updateMemoryBadgeInitial() {
    try {
      const stats = await API.getMemoryStats();
      if (tabMemoryBadge) tabMemoryBadge.textContent = stats.active_memories || stats.total_memories || 0;
    } catch {
      // Handled gracefully on startup
    }
  }

  // Initialize Submodules
  if (RAG.auth?.init) RAG.auth.init();
  if (RAG.rooms?.init) RAG.rooms.init();
  if (RAG.documents?.init) RAG.documents.init();
  if (RAG.memory?.init) RAG.memory.init();
  if (RAG.evidence?.init) RAG.evidence.init();
  if (RAG.settings?.init) RAG.settings.init();
  if (RAG.chat?.init) RAG.chat.init();

  // Initial Boot Data Ingestion
  if (RAG.auth?.updateAuthUI) RAG.auth.updateAuthUI();
  if (RAG.settings?.loadSettings) RAG.settings.loadSettings();
  if (RAG.documents?.loadDocuments) RAG.documents.loadDocuments();
  if (RAG.rooms?.loadRooms) RAG.rooms.loadRooms();
  updateMemoryBadgeInitial();

  RAG.app = {
    switchSidebarTab,
  };
  window.switchSidebarTab = switchSidebarTab;
});
