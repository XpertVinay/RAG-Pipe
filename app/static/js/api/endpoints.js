/**
 * Domain Specific API Endpoints (Auth, Rooms, Documents, Chat, Settings, Memory)
 */
(function (global) {
  'use strict';

  global.API = global.API || {};
  const API = global.API;

  // Authentication Endpoints
  API.register = async function (email, username, password, fullName = '', role = 'user', inviteToken = null) {
    const payload = {
      email,
      username,
      password,
      full_name: fullName || null,
      role: role || 'user',
    };
    if (inviteToken) {
      payload.invite_token = inviteToken;
    }
    const data = await API.post('/api/auth/register', payload);
    API.setAuthSession(data);
    return data;
  };

  API.login = async function (username, password) {
    const data = await API.post('/api/auth/login', { username, password });
    API.setAuthSession(data);
    return data;
  };

  API.refreshAuth = async function () {
    const refreshToken = API.getRefreshToken();
    if (!refreshToken) {
      API.clearAuthSession();
      return false;
    }
    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
      if (!res.ok) {
        API.clearAuthSession();
        return false;
      }
      const data = await res.json();
      API.setAuthSession(data);
      return true;
    } catch {
      API.clearAuthSession();
      return false;
    }
  };

  API.logout = async function () {
    const refreshToken = API.getRefreshToken();
    if (refreshToken) {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => {});
    }
    API.clearAuthSession();
  };

  API.getMe = async function () {
    return API.get('/api/auth/me');
  };

  // Room Workspace Endpoints
  API.getRooms = async function () {
    return API.get('/api/rooms');
  };

  API.createRoom = async function (name, description = '', isPublic = false) {
    return API.post('/api/rooms', { name, description, is_public: isPublic });
  };

  API.getRoom = async function (roomId) {
    return API.get(`/api/rooms/${roomId}`);
  };

  API.updateRoom = async function (roomId, data) {
    return API.put(`/api/rooms/${roomId}`, data);
  };

  API.deleteRoom = async function (roomId) {
    return API.delete(`/api/rooms/${roomId}`);
  };

  API.uploadFilesToRoom = async function (roomId, fileList) {
    const formData = new FormData();
    for (const file of fileList) {
      formData.append('files', file);
    }
    const headers = {};
    const token = API.getAccessToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(`/api/rooms/${roomId}/upload`, {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.detail || err.message || 'Upload to room failed');
    }
    return res.json();
  };

  API.attachDocumentToRoom = async function (roomId, docId) {
    return API.post(`/api/rooms/${roomId}/documents/${docId}`, {});
  };

  API.detachDocumentFromRoom = async function (roomId, docId) {
    return API.delete(`/api/rooms/${roomId}/documents/${docId}`);
  };

  API.getRoomReferences = async function (roomId) {
    return API.get(`/api/rooms/${roomId}/references`);
  };

  API.shareRoom = async function (roomId, isPublic) {
    return API.patch(`/api/rooms/${roomId}/share`, { is_public: isPublic });
  };

  API.getRoomMembers = async function (roomId) {
    return API.get(`/api/rooms/${roomId}/members`);
  };

  API.addRoomMember = async function (roomId, usernameOrEmail, role = 'viewer') {
    return API.post(`/api/rooms/${roomId}/members`, {
      username_or_email: usernameOrEmail,
      role: role,
    });
  };

  API.removeRoomMember = async function (roomId, userId) {
    return API.delete(`/api/rooms/${roomId}/members/${userId}`);
  };

  // Document Endpoints
  API.getDocuments = async function (status = null, scope = 'all') {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (scope) params.set('scope', scope);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return API.get(`/api/documents${qs}`);
  };

  API.uploadFiles = async function (fileList) {
    const formData = new FormData();
    for (const file of fileList) {
      formData.append('files', file);
    }
    const headers = {};
    const token = API.getAccessToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch('/api/documents/upload', {
      method: 'POST',
      headers,
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.detail || err.message || 'Upload failed');
    }
    return res.json();
  };

  API.deleteDocument = async function (docId) {
    return API.delete(`/api/documents/${docId}`);
  };

  API.shareDocument = async function (docId, isShared) {
    return API.patch(`/api/documents/${docId}/share`, { is_shared: isShared });
  };

  API.reprocessDocument = async function (docId) {
    return API.post(`/api/documents/${docId}/reprocess`, {});
  };

  API.getDocumentEvidence = async function (docId, page = 1, chunkId = null, query = '') {
    const params = new URLSearchParams();
    if (page) params.set('page', page);
    if (chunkId) params.set('chunk_id', chunkId);
    if (query) params.set('query', query);
    return API.get(`/api/documents/${docId}/evidence?${params.toString()}`);
  };

  API.getDocumentAudit = async function (docId) {
    return API.get(`/api/documents/${docId}/audit`);
  };

  API.getDocumentFileUrl = function (docId, page = 1) {
    const token = API.getAccessToken();
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
    return `/api/documents/${docId}/file${tokenParam}#page=${page}&view=FitH`;
  };

  // Chat & Conversation Endpoints
  API.getConversations = async function (roomId = null) {
    const q = roomId ? `?room_id=${encodeURIComponent(roomId)}` : '';
    return API.get(`/api/chat/conversations${q}`);
  };

  API.createConversation = async function (title = 'New Chat', roomId = null) {
    const q = new URLSearchParams({ title });
    if (roomId) q.append('room_id', roomId);
    return API.post(`/api/chat/conversations?${q.toString()}`, {});
  };

  API.getConversation = async function (convId) {
    return API.get(`/api/chat/conversations/${convId}`);
  };

  API.deleteConversation = async function (convId) {
    return API.delete(`/api/chat/conversations/${convId}`);
  };

  API.clearAllData = async function (roomId = null) {
    const q = roomId ? `?room_id=${encodeURIComponent(roomId)}` : '';
    return API.delete(`/api/chat/data/all${q}`);
  };

  // Settings, Health & Memory
  API.getSettings = async function () {
    return API.get('/api/settings');
  };

  API.updateSettings = async function (settings) {
    return API.post('/api/settings', settings);
  };

  API.getHealth = async function () {
    return API.get('/api/health');
  };

  API.listMemories = async function (params = {}) {
    const q = new URLSearchParams(params).toString();
    return API.get(`/api/memory${q ? '?' + q : ''}`);
  };

  API.createMemory = async function (payload) {
    return API.post('/api/memory', payload);
  };

  API.getMemoryStats = async function () {
    return API.get('/api/memory/stats');
  };

  API.revaluateMemories = async function (payload = {}) {
    return API.post('/api/memory/revaluate', payload);
  };

  API.deleteMemory = async function (memoryId) {
    return API.delete(`/api/memory/${memoryId}`);
  };

  API.pruneExpiredMemories = async function () {
    return API.delete('/api/memory/prune');
  };
})(window);
