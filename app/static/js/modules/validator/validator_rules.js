/**
 * Pure Validation Functions for Auth, Workspaces, Chat & Memory
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  RAG.validator = RAG.validator || {};

  const EMAIL_REGEX = /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$/;
  const USERNAME_REGEX = /^[a-zA-Z0-9_-]{3,50}$/;
  const MEMORY_KEY_REGEX = /^[a-zA-Z0-9_.:-]{2,120}$/;
  const MODEL_NAME_REGEX = /^[a-zA-Z0-9_.:/-]{1,100}$/;

  function validateEmail(value) {
    if (!value || typeof value !== 'string') return 'Email address is required.';
    const trimmed = value.trim();
    if (!trimmed) return 'Email address is required.';
    if (trimmed.length > 255) return 'Email address cannot exceed 255 characters.';
    if (!EMAIL_REGEX.test(trimmed)) return 'Please enter a valid email address (e.g. user@example.com).';
    return null;
  }

  function validateUsername(value) {
    if (!value || typeof value !== 'string') return 'Username is required.';
    const trimmed = value.trim();
    if (!trimmed) return 'Username is required.';
    if (trimmed.length < 3) return 'Username must be at least 3 characters.';
    if (trimmed.length > 50) return 'Username cannot exceed 50 characters.';
    if (!USERNAME_REGEX.test(trimmed)) return 'Username can only contain letters, numbers, hyphens (-), and underscores (_).';
    return null;
  }

  function validateLoginIdentifier(value) {
    if (!value || typeof value !== 'string') return 'Username or email address is required.';
    const trimmed = value.trim();
    if (!trimmed) return 'Username or email address is required.';
    if (trimmed.length < 3) return 'Identifier must be at least 3 characters.';
    if (trimmed.length > 100) return 'Identifier cannot exceed 100 characters.';
    return null;
  }

  function validatePassword(value, minLength = 6, maxLength = 100) {
    if (!value || typeof value !== 'string') return 'Password is required.';
    if (value.length < minLength) return `Password must be at least ${minLength} characters.`;
    if (value.length > maxLength) return `Password cannot exceed ${maxLength} characters.`;
    if (/^\s+$/.test(value)) return 'Password cannot consist solely of whitespace.';
    return null;
  }

  function validateFullName(value) {
    if (!value) return null;
    const trimmed = String(value).trim();
    if (trimmed.length > 100) return 'Full name cannot exceed 100 characters.';
    return null;
  }

  function validateRoomName(value) {
    if (!value || typeof value !== 'string') return 'Workspace room name is required.';
    const trimmed = value.trim();
    if (!trimmed) return 'Workspace room name cannot be empty.';
    if (trimmed.length < 2) return 'Workspace room name must be at least 2 characters.';
    if (trimmed.length > 150) return 'Workspace room name cannot exceed 150 characters.';
    return null;
  }

  function validateRoomDescription(value) {
    if (!value) return null;
    const trimmed = String(value).trim();
    if (trimmed.length > 500) return 'Description cannot exceed 500 characters.';
    return null;
  }

  function validateMemberIdentifier(value) {
    if (!value || typeof value !== 'string') return 'Please enter a team member\'s username or email.';
    const trimmed = value.trim();
    if (!trimmed) return 'Team member username or email cannot be empty.';
    if (trimmed.length < 3) return 'Identifier must be at least 3 characters.';
    if (trimmed.length > 100) return 'Identifier cannot exceed 100 characters.';
    return null;
  }

  function validateChatMessage(value) {
    if (!value || typeof value !== 'string') return 'Question query cannot be empty.';
    const trimmed = value.trim();
    if (!trimmed) return 'Question query cannot be empty.';
    if (trimmed.length > 4000) return `Question exceeds maximum length of 4,000 characters (current: ${trimmed.length}).`;
    return null;
  }

  function validateMemoryKey(value) {
    if (!value || typeof value !== 'string') return 'Semantic key / topic is required.';
    const trimmed = value.trim();
    if (!trimmed) return 'Semantic key cannot be empty.';
    if (trimmed.length < 2) return 'Semantic key must be at least 2 characters.';
    if (trimmed.length > 120) return 'Semantic key cannot exceed 120 characters.';
    if (!MEMORY_KEY_REGEX.test(trimmed)) {
      return 'Semantic key can only contain letters, numbers, colons (:), underscores (_), hyphens (-), and periods (.).';
    }
    return null;
  }

  function validateMemoryContent(value) {
    if (!value || typeof value !== 'string') return 'Distilled fact context is required.';
    const trimmed = value.trim();
    if (!trimmed) return 'Fact context cannot be empty.';
    if (trimmed.length < 3) return 'Fact context must be at least 3 characters.';
    if (trimmed.length > 5000) return 'Fact context cannot exceed 5,000 characters.';
    return null;
  }

  function validateMemoryImportance(value) {
    const num = parseFloat(value);
    if (isNaN(num) || num < 0.0 || num > 1.0) return 'Importance must be a decimal between 0.0 and 1.0.';
    return null;
  }

  function validateModelName(value) {
    if (!value) return null;
    const trimmed = String(value).trim();
    if (!trimmed) return null;
    if (trimmed.length > 100) return 'Model name cannot exceed 100 characters.';
    if (!MODEL_NAME_REGEX.test(trimmed)) return 'Model name contains invalid characters.';
    return null;
  }

  Object.assign(RAG.validator, {
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
  });
})(window);
