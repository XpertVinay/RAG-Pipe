/**
 * Client-Side JavaScript Input Validation & Visual Feedback Module
 * Production UX validation with instant real-time feedback, accessibility, and micro-animations
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  const ALLOWED_DOCUMENT_EXTENSIONS = ['pdf', 'docx', 'txt', 'md', 'csv', 'html'];
  const BLOCKED_EXECUTABLE_EXTENSIONS = [
    'exe', 'bat', 'cmd', 'sh', 'bash', 'bin', 'elf', 'dll', 'so', 'dylib',
    'py', 'pyc', 'pyd', 'js', 'vbs', 'vbe', 'wsf', 'wsh', 'ps1', 'psm1',
    'jar', 'war', 'ear', 'app', 'msi', 'scr', 'pif', 'hta', 'cpl'
  ];
  const MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB

  // Email format regex (RFC 5322 compliant simplified)
  const EMAIL_REGEX = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;

  // Alphanumeric, underscores, hyphens
  const USERNAME_REGEX = /^[a-zA-Z0-9_-]{3,50}$/;

  // Memory semantic descriptor: letters, digits, colons, underscores, hyphens, periods
  const MEMORY_KEY_REGEX = /^[a-zA-Z0-9_.:-]{2,120}$/;

  // Model names: letters, digits, colons, underscores, hyphens, slashes, periods
  const MODEL_NAME_REGEX = /^[a-zA-Z0-9_.:/-]{1,100}$/;

  // ---------------------------------------------------------------------------
  // Validation Pure Functions
  // ---------------------------------------------------------------------------

  function validateEmail(value) {
    if (!value || typeof value !== 'string') {
      return 'Email address is required.';
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return 'Email address is required.';
    }
    if (trimmed.length > 255) {
      return 'Email address cannot exceed 255 characters.';
    }
    if (!EMAIL_REGEX.test(trimmed)) {
      return 'Please enter a valid email address (e.g. user@example.com).';
    }
    return null;
  }

  function validateUsername(value) {
    if (!value || typeof value !== 'string') {
      return 'Username is required.';
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return 'Username is required.';
    }
    if (trimmed.length < 3) {
      return 'Username must be at least 3 characters.';
    }
    if (trimmed.length > 50) {
      return 'Username cannot exceed 50 characters.';
    }
    if (!USERNAME_REGEX.test(trimmed)) {
      return 'Username can only contain letters, numbers, hyphens (-), and underscores (_).';
    }
    return null;
  }

  function validateLoginIdentifier(value) {
    if (!value || typeof value !== 'string') {
      return 'Username or email address is required.';
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return 'Username or email address is required.';
    }
    if (trimmed.length < 3) {
      return 'Identifier must be at least 3 characters.';
    }
    if (trimmed.length > 100) {
      return 'Identifier cannot exceed 100 characters.';
    }
    return null;
  }

  function validatePassword(value, minLength = 6, maxLength = 100) {
    if (!value || typeof value !== 'string') {
      return 'Password is required.';
    }
    if (value.length < minLength) {
      return `Password must be at least ${minLength} characters.`;
    }
    if (value.length > maxLength) {
      return `Password cannot exceed ${maxLength} characters.`;
    }
    if (/^\s+$/.test(value)) {
      return 'Password cannot consist solely of whitespace.';
    }
    return null;
  }

  function validateFullName(value) {
    if (!value) return null;
    const trimmed = String(value).trim();
    if (trimmed.length > 100) {
      return 'Full name cannot exceed 100 characters.';
    }
    return null;
  }

  function validateRoomName(value) {
    if (!value || typeof value !== 'string') {
      return 'Workspace room name is required.';
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return 'Workspace room name cannot be empty.';
    }
    if (trimmed.length < 2) {
      return 'Workspace room name must be at least 2 characters.';
    }
    if (trimmed.length > 150) {
      return 'Workspace room name cannot exceed 150 characters.';
    }
    return null;
  }

  function validateRoomDescription(value) {
    if (!value) return null;
    const trimmed = String(value).trim();
    if (trimmed.length > 500) {
      return 'Description cannot exceed 500 characters.';
    }
    return null;
  }

  function validateMemberIdentifier(value) {
    if (!value || typeof value !== 'string') {
      return 'Please enter a team member\'s username or email.';
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return 'Team member username or email cannot be empty.';
    }
    if (trimmed.length < 3) {
      return 'Identifier must be at least 3 characters.';
    }
    if (trimmed.length > 100) {
      return 'Identifier cannot exceed 100 characters.';
    }
    return null;
  }

  function validateChatMessage(value) {
    if (!value || typeof value !== 'string') {
      return 'Question query cannot be empty.';
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return 'Question query cannot be empty.';
    }
    if (trimmed.length > 4000) {
      return `Question exceeds maximum length of 4,000 characters (current: ${trimmed.length}).`;
    }
    return null;
  }

  function validateMemoryKey(value) {
    if (!value || typeof value !== 'string') {
      return 'Semantic key / topic is required.';
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return 'Semantic key cannot be empty.';
    }
    if (trimmed.length < 2) {
      return 'Semantic key must be at least 2 characters.';
    }
    if (trimmed.length > 120) {
      return 'Semantic key cannot exceed 120 characters.';
    }
    if (!MEMORY_KEY_REGEX.test(trimmed)) {
      return 'Semantic key can only contain letters, numbers, colons (:), underscores (_), hyphens (-), and periods (.).';
    }
    return null;
  }

  function validateMemoryContent(value) {
    if (!value || typeof value !== 'string') {
      return 'Distilled fact context is required.';
    }
    const trimmed = value.trim();
    if (!trimmed) {
      return 'Fact context cannot be empty.';
    }
    if (trimmed.length < 3) {
      return 'Fact context must be at least 3 characters.';
    }
    if (trimmed.length > 5000) {
      return 'Fact context cannot exceed 5,000 characters.';
    }
    return null;
  }

  function validateMemoryImportance(value) {
    const num = parseFloat(value);
    if (isNaN(num) || num < 0.0 || num > 1.0) {
      return 'Importance must be a decimal between 0.0 and 1.0.';
    }
    return null;
  }

  function validateModelName(value) {
    if (!value) return null;
    const trimmed = String(value).trim();
    if (!trimmed) return null;
    if (trimmed.length > 100) {
      return 'Model name cannot exceed 100 characters.';
    }
    if (!MODEL_NAME_REGEX.test(trimmed)) {
      return 'Model name contains invalid characters.';
    }
    return null;
  }

  function validateFiles(fileList) {
    if (!fileList || fileList.length === 0) {
      return {
        valid: false,
        validFiles: [],
        rejectedFiles: [],
        message: 'No files selected for upload.'
      };
    }

    if (fileList.length > 15) {
      return {
        valid: false,
        validFiles: [],
        rejectedFiles: [],
        message: 'Upload limit exceeded. Maximum 15 files per batch allowed.'
      };
    }

    const validFiles = [];
    const rejectedFiles = [];

    Array.from(fileList).forEach((file) => {
      const name = file.name || 'unnamed';
      const parts = name.toLowerCase().split('.');
      const ext = parts.length > 1 ? parts.pop() : '';

      // Blocked executable extensions check
      if (parts.some((p) => BLOCKED_EXECUTABLE_EXTENSIONS.includes(p)) || BLOCKED_EXECUTABLE_EXTENSIONS.includes(ext)) {
        rejectedFiles.push({ file, reason: `Executable or script extension '.${ext}' is strictly forbidden for security.` });
        return;
      }

      // Allowed extensions check
      if (!ALLOWED_DOCUMENT_EXTENSIONS.includes(ext)) {
        rejectedFiles.push({ file, reason: `Extension '.${ext}' not permitted. Allowed: ${ALLOWED_DOCUMENT_EXTENSIONS.join(', ')}` });
        return;
      }

      // Zero bytes check
      if (file.size === 0) {
        rejectedFiles.push({ file, reason: 'File is empty (0 bytes).' });
        return;
      }

      // Max size check (25MB)
      if (file.size > MAX_FILE_SIZE_BYTES) {
        const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
        rejectedFiles.push({ file, reason: `File size (${sizeMb} MB) exceeds maximum permitted limit of 25 MB.` });
        return;
      }

      validFiles.push(file);
    });

    return {
      valid: rejectedFiles.length === 0 && validFiles.length > 0,
      validFiles,
      rejectedFiles,
      message: rejectedFiles.length > 0
        ? `${rejectedFiles.length} file(s) failed validation: ${rejectedFiles.map((r) => `${r.file.name} (${r.reason})`).join('; ')}`
        : null
    };
  }

  // ---------------------------------------------------------------------------
  // DOM Validation Visual Feedback & UI/UX Helpers
  // ---------------------------------------------------------------------------

  function showError(inputEl, message) {
    if (!inputEl) return;
    inputEl.classList.add('is-invalid');
    inputEl.classList.remove('is-valid');
    inputEl.setAttribute('aria-invalid', 'true');

    // Remove any existing error message
    const existing = inputEl.parentNode ? inputEl.parentNode.querySelector(`.field-error-msg[data-for="${inputEl.id || ''}"]`) : null;
    if (existing) existing.remove();

    if (message) {
      const errEl = document.createElement('div');
      errEl.className = 'field-error-msg';
      if (inputEl.id) errEl.setAttribute('data-for', inputEl.id);
      errEl.innerHTML = `<span style="font-size: 0.82rem;">⚠️</span> <span>${RAG.utils.escapeHtml(message)}</span>`;

      // Insert immediately after inputEl
      if (inputEl.nextSibling) {
        inputEl.parentNode.insertBefore(errEl, inputEl.nextSibling);
      } else {
        inputEl.parentNode.appendChild(errEl);
      }
    }

    // Micro-animation shake
    inputEl.classList.remove('input-shake');
    // Force reflow
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
      // If currently showing error, re-validate dynamically
      if (inputEl.classList.contains('is-invalid')) {
        const err = validatorFn(inputEl.value);
        if (!err) {
          clearError(inputEl);
        } else {
          // Update error text without shaking
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

  // ---------------------------------------------------------------------------
  // Module Export
  // ---------------------------------------------------------------------------

  // Suppress default native browser popover validation bubbles globally across all inputs and forms
  document.addEventListener(
    'invalid',
    (e) => {
      e.preventDefault();
    },
    true
  );

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

  RAG.validator = {
    // Pure validators
    validateEmail,
    validateUsername,
    validateLoginIdentifier,
    validatePassword,
    validateFullName,
    validateRoomName,
    validateRoomDescription,
    validateMemberIdentifier,
    validateChatMessage,
    validateMemoryKey,
    validateMemoryContent,
    validateMemoryImportance,
    validateModelName,
    validateFiles,

    // UI helpers
    showError,
    clearError,
    markValid,
    attachLiveValidation,
    disableNativeValidationGlobally,

    // Constants
    ALLOWED_DOCUMENT_EXTENSIONS,
    BLOCKED_EXECUTABLE_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
  };

  global.RAGValidator = RAG.validator;
})(window);
