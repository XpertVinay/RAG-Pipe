/**
 * Document Batch & File Security Extension Validators
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.validator = RAG.validator || {};

  const ALLOWED_DOCUMENT_EXTENSIONS = ['pdf', 'docx', 'txt', 'md', 'csv', 'html'];
  const BLOCKED_EXECUTABLE_EXTENSIONS = [
    'exe', 'bat', 'cmd', 'sh', 'bash', 'bin', 'elf', 'dll', 'so', 'dylib',
    'py', 'pyc', 'pyd', 'js', 'vbs', 'vbe', 'wsf', 'wsh', 'ps1', 'psm1',
    'jar', 'war', 'ear', 'app', 'msi', 'scr', 'pif', 'hta', 'cpl',
  ];
  const MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024; // 25 MB

  function validateFiles(fileList) {
    if (!fileList || fileList.length === 0) {
      return {
        valid: false,
        validFiles: [],
        rejectedFiles: [],
        message: 'No files selected for upload.',
      };
    }

    if (fileList.length > 15) {
      return {
        valid: false,
        validFiles: [],
        rejectedFiles: [],
        message: 'Upload limit exceeded. Maximum 15 files per batch allowed.',
      };
    }

    const validFiles = [];
    const rejectedFiles = [];

    Array.from(fileList).forEach((file) => {
      const name = file.name || 'unnamed';
      const parts = name.toLowerCase().split('.');
      const ext = parts.length > 1 ? parts.pop() : '';

      if (parts.some((p) => BLOCKED_EXECUTABLE_EXTENSIONS.includes(p)) || BLOCKED_EXECUTABLE_EXTENSIONS.includes(ext)) {
        rejectedFiles.push({ file, reason: `Executable or script extension '.${ext}' is strictly forbidden for security.` });
        return;
      }

      if (!ALLOWED_DOCUMENT_EXTENSIONS.includes(ext)) {
        rejectedFiles.push({ file, reason: `Extension '.${ext}' not permitted. Allowed: ${ALLOWED_DOCUMENT_EXTENSIONS.join(', ')}` });
        return;
      }

      if (file.size === 0) {
        rejectedFiles.push({ file, reason: 'File is empty (0 bytes).' });
        return;
      }

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
        : null,
    };
  }

  RAG.validator.ALLOWED_DOCUMENT_EXTENSIONS = ALLOWED_DOCUMENT_EXTENSIONS;
  RAG.validator.BLOCKED_EXECUTABLE_EXTENSIONS = BLOCKED_EXECUTABLE_EXTENSIONS;
  RAG.validator.MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_BYTES;
  RAG.validator.validateFiles = validateFiles;
})(window);
