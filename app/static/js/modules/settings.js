/**
 * Model & Retrieval Settings Module
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  async function loadSettings() {
    const providerBadge = document.getElementById('provider-badge');
    const providerSelect = document.getElementById('provider-select');
    const modelInput = document.getElementById('model-input');
    const embeddingProviderSelect = document.getElementById('embedding-provider-select');
    const embeddingModelInput = document.getElementById('embedding-model-input');
    const topkSlider = document.getElementById('topk-slider');
    const topkVal = document.getElementById('topk-val');

    try {
      const s = await API.getSettings();
      RAG.state.activeSettings = s;
      if (providerBadge) {
        providerBadge.textContent = `${s.default_chat_provider.toUpperCase()} / ${s.default_chat_model.toUpperCase()}`;
      }
      if (providerSelect) providerSelect.value = s.default_chat_provider;
      if (modelInput) modelInput.value = s.default_chat_model;
      if (embeddingProviderSelect) embeddingProviderSelect.value = s.default_embedding_provider;
      if (embeddingModelInput) embeddingModelInput.value = s.default_embedding_model;
      if (topkSlider) topkSlider.value = s.retrieval_top_k;
      if (topkVal) topkVal.textContent = s.retrieval_top_k;
    } catch (e) {
      console.warn('Failed to load settings:', e);
    }
  }

  function initSettingsListeners() {
    const openSettingsBtn = document.getElementById('open-settings-btn');
    const settingsModal = document.getElementById('settings-modal');
    const closeSettingsBtn = document.getElementById('close-settings-btn');
    const saveSettingsBtn = document.getElementById('save-settings-btn');
    const providerSelect = document.getElementById('provider-select');
    const modelInput = document.getElementById('model-input');
    const embeddingProviderSelect = document.getElementById('embedding-provider-select');
    const embeddingModelInput = document.getElementById('embedding-model-input');
    const topkSlider = document.getElementById('topk-slider');
    const topkVal = document.getElementById('topk-val');
    const providerBadge = document.getElementById('provider-badge');

    const resetSettingsErrors = () => {
      if (RAG.validator) {
        if (modelInput) RAG.validator.clearError(modelInput);
        if (embeddingModelInput) RAG.validator.clearError(embeddingModelInput);
      }
      settingsModal?.classList.remove('active');
    };

    openSettingsBtn?.addEventListener('click', () => {
      if (RAG.validator) {
        if (modelInput) RAG.validator.clearError(modelInput);
        if (embeddingModelInput) RAG.validator.clearError(embeddingModelInput);
      }
      settingsModal?.classList.add('active');
    });
    closeSettingsBtn?.addEventListener('click', resetSettingsErrors);

    if (RAG.validator) {
      if (modelInput) RAG.validator.attachLiveValidation(modelInput, RAG.validator.validateModelName);
      if (embeddingModelInput) RAG.validator.attachLiveValidation(embeddingModelInput, RAG.validator.validateModelName);
    }

    topkSlider?.addEventListener('input', (e) => {
      if (topkVal) topkVal.textContent = e.target.value;
    });

    saveSettingsBtn?.addEventListener('click', async () => {
      const chatModelVal = modelInput?.value.trim() || '';
      const embedModelVal = embeddingModelInput?.value.trim() || '';

      // JavaScript Input Validation
      if (RAG.validator) {
        const chatModelErr = RAG.validator.validateModelName(chatModelVal);
        if (chatModelErr) {
          RAG.validator.showError(modelInput, chatModelErr);
          modelInput?.focus();
          return;
        } else if (modelInput) {
          RAG.validator.clearError(modelInput);
        }

        const embedModelErr = RAG.validator.validateModelName(embedModelVal);
        if (embedModelErr) {
          RAG.validator.showError(embeddingModelInput, embedModelErr);
          embeddingModelInput?.focus();
          return;
        } else if (embeddingModelInput) {
          RAG.validator.clearError(embeddingModelInput);
        }
      }

      try {
        const updated = await API.updateSettings({
          default_chat_provider: providerSelect.value,
          default_chat_model: chatModelVal || undefined,
          default_embedding_provider: embeddingProviderSelect?.value || undefined,
          default_embedding_model: embedModelVal || undefined,
          retrieval_top_k: parseInt(topkSlider.value, 10),
        });
        if (RAG.state.activeSettings) {
          RAG.state.activeSettings.default_chat_provider = updated.active_chat_provider;
          RAG.state.activeSettings.default_chat_model = updated.active_chat_model;
          RAG.state.activeSettings.default_embedding_provider = updated.active_embedding_provider;
          RAG.state.activeSettings.default_embedding_model = updated.active_embedding_model;
          RAG.state.activeSettings.retrieval_top_k = updated.retrieval_top_k;
        }
        if (providerBadge) {
          providerBadge.textContent = `${updated.active_chat_provider.toUpperCase()} / ${updated.active_chat_model}`;
        }
        resetSettingsErrors();
        RAG.utils.showToast('Settings saved successfully', 'success');
      } catch (e) {
        RAG.utils.showToast(e.message, 'error');
      }
    });
  }

  RAG.settings = {
    loadSettings,
    init: initSettingsListeners,
  };

  global.loadSettings = loadSettings;
})(window);
