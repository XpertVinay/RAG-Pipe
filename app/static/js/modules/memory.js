/**
 * Two-Tier Context Memory Module (Global vs User Specific, STM vs LTM)
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  let currentMemoryFilter = 'all';
  let cachedMemoryItems = [];

  async function loadMemoryDashboard() {
    const memoryList = document.getElementById('memory-list');
    const tabMemoryBadge = document.getElementById('tab-memory-badge');
    const memL1Bytes = document.getElementById('mem-l1-bytes');
    const memActiveTotal = document.getElementById('mem-active-total');
    const memHitRate = document.getElementById('mem-hit-rate');
    const currentUser = API.getCurrentUser();
    const isAdminOrStaff = Boolean(
      currentUser &&
      API.getAccessToken() &&
      (currentUser.role === 'admin' || currentUser.role === 'staff' || currentUser.role === 'staffs')
    );

    if (!isAdminOrStaff) {
      if (tabMemoryBadge) tabMemoryBadge.textContent = '0';
      if (memL1Bytes) memL1Bytes.textContent = '0 KB';
      if (memActiveTotal) memActiveTotal.textContent = '0 / 0';
      if (memHitRate) memHitRate.textContent = '100%';
      if (memoryList) {
        memoryList.innerHTML = `
          <div style="text-align: center; padding: 28px 10px; color: var(--text-muted); font-size: 0.8rem;">
            <span>Short-term and long-term memory inspection is restricted to admin and staff members.</span>
          </div>
        `;
      }
      return;
    }

    try {
      const stats = await API.getMemoryStats();
      if (tabMemoryBadge) tabMemoryBadge.textContent = stats.active_memories || stats.total_memories || 0;

      if (memL1Bytes) {
        const kb = (stats.in_memory_l1_bytes / 1024).toFixed(1);
        memL1Bytes.textContent = `${kb} KB`;
      }
      if (memActiveTotal) {
        memActiveTotal.textContent = `${stats.active_memories} / ${stats.total_memories}`;
      }
      if (memHitRate) {
        const totalReq = stats.cache_hits + stats.cache_misses;
        const rate = totalReq > 0 ? Math.round((stats.cache_hits / totalReq) * 100) : 100;
        memHitRate.textContent = `${rate}%`;
      }

      const params = {};
      if (currentMemoryFilter === 'global') params.scope = 'global';
      if (currentMemoryFilter === 'user_specific') params.scope = 'user_specific';
      if (currentMemoryFilter === 'short_term') params.memory_type = 'short_term';
      if (currentMemoryFilter === 'long_term') params.memory_type = 'long_term';

      const items = await API.listMemories(params);
      cachedMemoryItems = items || [];

      if (!memoryList) return;

      if (!items || items.length === 0) {
        memoryList.innerHTML = `
          <div style="text-align: center; padding: 24px 10px; color: var(--text-muted); font-size: 0.78rem;">
            No ${currentMemoryFilter !== 'all' ? currentMemoryFilter : ''} memories saved yet.<br>
            <span style="font-size: 0.7rem; color: var(--text-dim);">Memories automatically synthesize from chat turns or can be added manually.</span>
          </div>
        `;
        return;
      }

      memoryList.innerHTML = items
        .map((m) => {
          const isGlobal = m.scope === 'global';
          const isStm = m.memory_type === 'short_term';
          const scopeBadgeClass = isGlobal ? 'mem-badge-global' : 'mem-badge-user';
          const typeBadgeClass = isStm ? 'mem-badge-stm' : 'mem-badge-ltm';

          let expiryText = 'No Expiry';
          if (m.expires_at) {
            const expDate = new Date(m.expires_at);
            const diffMin = Math.round((expDate - new Date()) / 60000);
            if (diffMin <= 0) {
              expiryText = '<span style="color: #ef4444;">Expired</span>';
            } else if (diffMin < 60) {
              expiryText = `Expires in ${diffMin}m`;
            } else {
              const diffHours = Math.round(diffMin / 60);
              expiryText = `Expires in ${diffHours}h`;
            }
          }

          const revalBadge = m.needs_revaluation
            ? `<span class="mem-badge mem-badge-reval">Stale (Reval Req)</span>`
            : '';

          return `
            <div class="memory-card">
              <div class="memory-card-header">
                <span class="memory-card-key" title="${RAG.utils.escapeHtml(m.key)}">${RAG.utils.escapeHtml(m.key)}</span>
                <div class="memory-badges">
                  ${revalBadge}
                  <span class="mem-badge ${scopeBadgeClass}">${isGlobal ? 'Global' : 'User'}</span>
                  <span class="mem-badge ${typeBadgeClass}">${isStm ? 'STM' : 'LTM'}</span>
                </div>
              </div>
              <div class="memory-card-content">${RAG.utils.escapeHtml(m.content)}</div>
              <div class="memory-card-footer">
                <span>${expiryText}</span>
                <div class="memory-card-actions">
                  <span title="Importance score">★ ${(m.importance || 0.5).toFixed(1)}</span>
                  <button class="mem-btn-icon" type="button" onclick="event.stopPropagation(); event.preventDefault(); window.deleteMemoryItem('${m.id}', event)" title="Delete fact">🗑️</button>
                </div>
              </div>
            </div>
          `;
        })
        .join('');
    } catch (e) {
      console.warn('Failed to load memory dashboard:', e);
      if (memoryList) {
        memoryList.innerHTML = `
          <div style="text-align: center; padding: 20px 10px; color: var(--text-muted); font-size: 0.78rem;">
            Unable to load memory items: ${RAG.utils.escapeHtml(e.message)}
          </div>
        `;
      }
    }
  }

  async function deleteMemoryItem(memoryId, ev) {
    if (ev) {
      ev.stopPropagation();
      ev.preventDefault();
    }
    const memItem = (cachedMemoryItems || []).find((x) => x.id === memoryId);
    const key = memItem ? memItem.key : 'Memory Fact';
    const content = memItem ? memItem.content : '';
    const isGlobal = memItem?.scope === 'global';
    const isStm = memItem?.memory_type === 'short_term';
    const scopeTag = isGlobal ? 'Global' : 'User';
    const typeTag = isStm ? 'STM' : 'LTM';

    RAG.utils.showConfirmModal({
      title: 'Delete Memory Fact',
      headerIcon: '🗑️',
      itemIcon: '🧠',
      itemName: key,
      itemMeta: `[${scopeTag}:${typeTag}] ${content ? content.slice(0, 100) : ''}`,
      prompt: `Are you sure you want to delete "${key}"? This will invalidate L1 in-memory cache and remove the record permanently from the database.`,
      confirmText: 'Delete Fact',
      onConfirm: async () => {
        try {
          await API.deleteMemory(memoryId);
          RAG.utils.showToast('Memory item removed.', 'info');
          await loadMemoryDashboard();
        } catch (e) {
          RAG.utils.showToast('Delete failed: ' + e.message, 'error');
        }
      },
    });
  }

  function initMemoryListeners() {
    const revalMemBtn = document.getElementById('reval-mem-btn');
    const pruneMemoryBtn = document.getElementById('prune-memory-btn');
    const addMemoryBtn = document.getElementById('add-memory-btn');
    const memoryModal = document.getElementById('memory-modal');
    const closeMemoryModalBtn = document.getElementById('close-memory-modal-btn');
    const cancelMemoryBtn = document.getElementById('cancel-memory-btn');
    const memoryForm = document.getElementById('memory-form');

    document.querySelectorAll('.mem-chip').forEach((chip) => {
      chip.addEventListener('click', () => {
        document.querySelectorAll('.mem-chip').forEach((c) => c.classList.remove('active'));
        chip.classList.add('active');
        currentMemoryFilter = chip.getAttribute('data-scope-filter') || 'all';
        loadMemoryDashboard();
      });
    });

    revalMemBtn?.addEventListener('click', async () => {
      revalMemBtn.disabled = true;
      revalMemBtn.textContent = '⏳ Scanning...';
      try {
        const res = await API.revaluateMemories();
        RAG.utils.showToast(res.message || 'Revaluation complete.', 'success');
        await loadMemoryDashboard();
      } catch (e) {
        RAG.utils.showToast('Revaluation failed: ' + e.message, 'error');
      } finally {
        revalMemBtn.disabled = false;
        revalMemBtn.textContent = '🔄 Reval';
      }
    });

    pruneMemoryBtn?.addEventListener('click', async () => {
      pruneMemoryBtn.disabled = true;
      try {
        const res = await API.pruneExpiredMemories();
        RAG.utils.showToast(res.message || 'Pruned expired memories.', 'success');
        await loadMemoryDashboard();
      } catch (e) {
        RAG.utils.showToast('Failed to prune memories: ' + e.message, 'error');
      } finally {
        pruneMemoryBtn.disabled = false;
      }
    });

    addMemoryBtn?.addEventListener('click', () => {
      if (memoryModal) memoryModal.classList.add('active');
    });

    const memKeyInput = document.getElementById('mem-key-input');
    const memContentInput = document.getElementById('mem-content-input');
    const memImportanceInput = document.getElementById('mem-importance-input');

    if (RAG.validator) {
      if (memKeyInput) RAG.validator.attachLiveValidation(memKeyInput, RAG.validator.validateMemoryKey);
      if (memContentInput) RAG.validator.attachLiveValidation(memContentInput, RAG.validator.validateMemoryContent);
      if (memImportanceInput) RAG.validator.attachLiveValidation(memImportanceInput, RAG.validator.validateMemoryImportance);
    }

    const resetMemoryModal = () => {
      if (RAG.validator) {
        if (memKeyInput) RAG.validator.clearError(memKeyInput);
        if (memContentInput) RAG.validator.clearError(memContentInput);
        if (memImportanceInput) RAG.validator.clearError(memImportanceInput);
      }
      if (memoryModal) memoryModal.classList.remove('active');
    };

    closeMemoryModalBtn?.addEventListener('click', resetMemoryModal);
    cancelMemoryBtn?.addEventListener('click', resetMemoryModal);

    memoryForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const scope = document.getElementById('mem-scope-select')?.value || 'global';
      const memory_type = document.getElementById('mem-type-select')?.value || 'short_term';
      const key = memKeyInput?.value.trim() || '';
      const content = memContentInput?.value.trim() || '';
      const importanceVal = memImportanceInput?.value || '0.7';
      const importance = parseFloat(importanceVal);

      // JavaScript Input Validation
      if (RAG.validator) {
        const keyErr = RAG.validator.validateMemoryKey(key);
        if (keyErr) {
          RAG.validator.showError(memKeyInput, keyErr);
          memKeyInput?.focus();
          return;
        } else {
          RAG.validator.clearError(memKeyInput);
        }

        const contentErr = RAG.validator.validateMemoryContent(content);
        if (contentErr) {
          RAG.validator.showError(memContentInput, contentErr);
          memContentInput?.focus();
          return;
        } else {
          RAG.validator.clearError(memContentInput);
        }

        const impErr = RAG.validator.validateMemoryImportance(importanceVal);
        if (impErr) {
          RAG.validator.showError(memImportanceInput, impErr);
          memImportanceInput?.focus();
          return;
        } else {
          RAG.validator.clearError(memImportanceInput);
        }
      }

      try {
        await API.createMemory({
          scope,
          memory_type,
          key,
          content,
          importance,
        });
        RAG.utils.showToast(`Fact '${key}' saved to ${scope} ${memory_type} memory.`, 'success');
        resetMemoryModal();
        memoryForm.reset();
        await loadMemoryDashboard();
      } catch (err) {
        if (memKeyInput && RAG.validator) {
          RAG.validator.showError(memKeyInput, err.message);
        }
        RAG.utils.showToast('Failed to save memory: ' + err.message, 'error');
      }
    });
  }

  RAG.memory = {
    loadMemoryDashboard,
    deleteMemoryItem,
    init: initMemoryListeners,
  };

  global.loadMemoryDashboard = loadMemoryDashboard;
  global.deleteMemoryItem = deleteMemoryItem;
})(window);
