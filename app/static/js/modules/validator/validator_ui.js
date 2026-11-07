/**
 * DOM Validation Visual Feedback, Error Messages, Shakes & Live Listeners
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.validator = RAG.validator || {};

  function showError(inputEl, message) {
    if (!inputEl) return;
    inputEl.classList.add('is-invalid');
    inputEl.classList.remove('is-valid');
    inputEl.setAttribute('aria-invalid', 'true');

    const existing = inputEl.parentNode ? inputEl.parentNode.querySelector(`.field-error-msg[data-for="${inputEl.id || ''}"]`) : null;
    if (existing) existing.remove();

    if (message) {
      const errEl = document.createElement('div');
      errEl.className = 'field-error-msg';
      if (inputEl.id) errEl.setAttribute('data-for', inputEl.id);
      errEl.innerHTML = `<span style="font-size: 0.82rem;">⚠️</span> <span>${RAG.utils.escapeHtml(message)}</span>`;

      if (inputEl.nextSibling) {
        inputEl.parentNode.insertBefore(errEl, inputEl.nextSibling);
      } else {
        inputEl.parentNode.appendChild(errEl);
      }
    }

    inputEl.classList.remove('input-shake');
    void inputEl.offsetWidth;
    inputEl.classList.add('input-shake');
    setTimeout(() => {
      inputEl.classList.remove('input-shake');
    }, 400);
  }

  function clearError(inputEl) {
    if (!inputEl) return;
    inputEl.classList.remove('is-invalid');
    inputEl.classList.remove('input-shake');
    inputEl.setAttribute('aria-invalid', 'false');

    const existing = inputEl.parentNode ? inputEl.parentNode.querySelector(`.field-error-msg[data-for="${inputEl.id || ''}"]`) : null;
    if (existing) existing.remove();
  }

  function markValid(inputEl) {
    if (!inputEl) return;
    clearError(inputEl);
    inputEl.classList.add('is-valid');
  }

  function attachLiveValidation(inputEl, validatorFn) {
    if (!inputEl || typeof validatorFn !== 'function') return;

    inputEl.addEventListener('input', () => {
      if (inputEl.classList.contains('is-invalid')) {
        const err = validatorFn(inputEl.value);
        if (!err) {
          clearError(inputEl);
        } else {
          const msgEl = inputEl.parentNode?.querySelector(`.field-error-msg[data-for="${inputEl.id || ''}"] span:last-child`);
          if (msgEl) msgEl.textContent = err;
        }
      }
    });

    inputEl.addEventListener('blur', () => {
      const err = validatorFn(inputEl.value);
      if (err) {
        showError(inputEl, err);
      } else if (inputEl.value.trim()) {
        markValid(inputEl);
      } else {
        clearError(inputEl);
      }
    });
  }

  document.addEventListener('invalid', (e) => e.preventDefault(), true);

  function disableNativeValidationGlobally() {
    document.querySelectorAll('form').forEach((form) => {
      form.setAttribute('novalidate', '');
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', disableNativeValidationGlobally);
  } else {
    disableNativeValidationGlobally();
  }

  RAG.validator.showError = showError;
  RAG.validator.clearError = clearError;
  RAG.validator.markValid = markValid;
  RAG.validator.attachLiveValidation = attachLiveValidation;
  RAG.validator.disableNativeValidationGlobally = disableNativeValidationGlobally;
})(window);
