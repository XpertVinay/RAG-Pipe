/**
 * Production RAG Agent Client API Service
 * Comprehensive JWT Token Management, Auto-Refresh, Room Workspaces, and Database References
 */
const API = {
  TOKEN_KEY: 'rag_access_token',
  ID_TOKEN_KEY: 'rag_id_token',
  REFRESH_TOKEN_KEY: 'rag_refresh_token',
  USER_KEY: 'rag_user',
  ACTIVE_ROOM_KEY: 'rag_active_room_id',

  // --------------------------------------------------------------------------
  // Token & Session Storage Management
  // --------------------------------------------------------------------------
  getAccessToken() {
    return localStorage.getItem(this.TOKEN_KEY);
  },

  getIdToken() {
    return localStorage.getItem(this.ID_TOKEN_KEY);
  },

  getRefreshToken() {
    return localStorage.getItem(this.REFRESH_TOKEN_KEY);
  },

  getCurrentUser() {
    try {
      const u = localStorage.getItem(this.USER_KEY);
      return u ? JSON.parse(u) : null;
    } catch {
      return null;
    }
  },

  getActiveRoomId() {
    return localStorage.getItem(this.ACTIVE_ROOM_KEY);
  },

  setActiveRoomId(roomId) {
    if (roomId) {
      localStorage.setItem(this.ACTIVE_ROOM_KEY, roomId);
    } else {
      localStorage.removeItem(this.ACTIVE_ROOM_KEY);
    }
  },

  syncCookieToken() {
    const token = this.getAccessToken();
    if (token) {
      document.cookie = `access_token=${encodeURIComponent(token)}; path=/; max-age=604800; SameSite=Lax`;
    }
  },

  setAuthSession(tokenData) {
    if (tokenData.access_token) {
      localStorage.setItem(this.TOKEN_KEY, tokenData.access_token);
      document.cookie = `access_token=${encodeURIComponent(tokenData.access_token)}; path=/; max-age=604800; SameSite=Lax`;
    }
    if (tokenData.id_token) {
      localStorage.setItem(this.ID_TOKEN_KEY, tokenData.id_token);
    }
    if (tokenData.refresh_token) {
      localStorage.setItem(this.REFRESH_TOKEN_KEY, tokenData.refresh_token);
    }
    if (tokenData.user) {
      localStorage.setItem(this.USER_KEY, JSON.stringify(tokenData.user));
    }
  },

  clearAuthSession() {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.ID_TOKEN_KEY);
    localStorage.removeItem(this.REFRESH_TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
    localStorage.removeItem(this.ACTIVE_ROOM_KEY);
    localStorage.removeItem('rag_active_conv_id');
    document.cookie = 'access_token=; path=/; max-age=0; SameSite=Lax';
    document.cookie = 'token=; path=/; max-age=0; SameSite=Lax';
  },

  // --------------------------------------------------------------------------
  // Core Fetch with Authorization and Automatic Token Refresh
  // --------------------------------------------------------------------------
  async request(url, options = {}, isRetry = false) {
    const headers = options.headers || {};
    const token = this.getAccessToken();

    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(url, { ...options, headers });

    // Handle 401 Unauthorized by attempting a token refresh once
    if (res.status === 401 && !isRetry && !url.includes('/api/auth/')) {
      const refreshed = await this.refreshAuth();
      if (refreshed) {
        return this.request(url, options, true);
      }
      this.clearAuthSession();
      if (window.showAuthModal) {
        window.showAuthModal('signin', 'Authentication required. Please sign in or register.');
      }
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      let detailMsg = err.detail || err.message;
      if (Array.isArray(detailMsg)) {
        detailMsg = detailMsg
          .map((d) => (d.loc ? `${d.loc.filter((x) => x !== 'body').join('.')}: ${d.msg}` : d.msg || JSON.stringify(d)))
          .join('; ');
      } else if (typeof detailMsg === 'object' && detailMsg !== null) {
        detailMsg = detailMsg.msg || detailMsg.message || JSON.stringify(detailMsg);
      }
      throw new Error(detailMsg || 'API request failed');
    }

    return res.json();
  },

  async get(url) {
    return this.request(url, { method: 'GET' });
  },

  async post(url, data) {
    return this.request(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  async put(url, data) {
    return this.request(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  async patch(url, data) {
    return this.request(url, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  async delete(url) {
    return this.request(url, { method: 'DELETE' });
  },

  // --------------------------------------------------------------------------
  // Authentication & Authorization Endpoints
  // --------------------------------------------------------------------------
  async register(email, username, password, fullName = '', role = 'user') {
    const data = await this.post('/api/auth/register', {
      email,
      username,
      password,
      full_name: fullName || null,
      role: role || 'user',
    });
    this.setAuthSession(data);
    return data;
  },

  async login(username, password) {
    const data = await this.post('/api/auth/login', {
      username,
      password,
    });
    this.setAuthSession(data);
    return data;
  },

  async refreshAuth() {
    const refreshToken = this.getRefreshToken();
    if (!refreshToken) {
      this.clearAuthSession();
      return false;
    }

    try {
      const res = await fetch('/api/auth/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!res.ok) {
        this.clearAuthSession();
        return false;
      }

      const data = await res.json();
      this.setAuthSession(data);
      return true;
    } catch {
      this.clearAuthSession();
      return false;
    }
  },

  async logout() {
    const refreshToken = this.getRefreshToken();
    if (refreshToken) {
      await fetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => {});
    }
    this.clearAuthSession();
  },

  async getMe() {
    return this.get('/api/auth/me');
  },

  // --------------------------------------------------------------------------
  // Room Workspace Endpoints
  // --------------------------------------------------------------------------
  async getRooms() {
    return this.get('/api/rooms');
  },

  async createRoom(name, description = '', isPublic = false) {
    return this.post('/api/rooms', { name, description, is_public: isPublic });
  },

  async getRoom(roomId) {
    return this.get(`/api/rooms/${roomId}`);
  },

  async updateRoom(roomId, data) {
    return this.put(`/api/rooms/${roomId}`, data);
  },

  async deleteRoom(roomId) {
    return this.delete(`/api/rooms/${roomId}`);
  },

  async uploadFilesToRoom(roomId, fileList) {
    const formData = new FormData();
    for (const file of fileList) {
      formData.append('files', file);
    }
    const headers = {};
    const token = this.getAccessToken();
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
  },

  async attachDocumentToRoom(roomId, docId) {
    return this.post(`/api/rooms/${roomId}/documents/${docId}`, {});
  },

  async detachDocumentFromRoom(roomId, docId) {
    return this.delete(`/api/rooms/${roomId}/documents/${docId}`);
  },

  async getRoomReferences(roomId) {
    return this.get(`/api/rooms/${roomId}/references`);
  },

  async shareRoom(roomId, isPublic) {
    return this.patch(`/api/rooms/${roomId}/share`, { is_public: isPublic });
  },

  async getRoomMembers(roomId) {
    return this.get(`/api/rooms/${roomId}/members`);
  },

  async addRoomMember(roomId, usernameOrEmail, role = 'viewer') {
    return this.post(`/api/rooms/${roomId}/members`, {
      username_or_email: usernameOrEmail,
      role: role,
    });
  },

  async removeRoomMember(roomId, userId) {
    return this.delete(`/api/rooms/${roomId}/members/${userId}`);
  },

  // --------------------------------------------------------------------------
  // Document Endpoints
  // --------------------------------------------------------------------------
  async getDocuments(status = null, scope = 'all') {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (scope) params.set('scope', scope);
    const qs = params.toString() ? `?${params.toString()}` : '';
    return this.get(`/api/documents${qs}`);
  },

  async uploadFiles(fileList) {
    const formData = new FormData();
    for (const file of fileList) {
      formData.append('files', file);
    }
    const headers = {};
    const token = this.getAccessToken();
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
  },

  async deleteDocument(docId) {
    return this.delete(`/api/documents/${docId}`);
  },

  async shareDocument(docId, isShared) {
    return this.patch(`/api/documents/${docId}/share`, { is_shared: isShared });
  },

  async reprocessDocument(docId) {
    return this.post(`/api/documents/${docId}/reprocess`, {});
  },

  async getDocumentEvidence(docId, page = 1, chunkId = null, query = '') {
    const params = new URLSearchParams();
    if (page) params.set('page', page);
    if (chunkId) params.set('chunk_id', chunkId);
    if (query) params.set('query', query);
    return this.get(`/api/documents/${docId}/evidence?${params.toString()}`);
  },

  async getDocumentAudit(docId) {
    return this.get(`/api/documents/${docId}/audit`);
  },

  getDocumentFileUrl(docId, page = 1) {
    const token = this.getAccessToken();
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
    return `/api/documents/${docId}/file${tokenParam}#page=${page}&view=FitH`;
  },

  // --------------------------------------------------------------------------
  // Chat & Conversation Endpoints
  // --------------------------------------------------------------------------
  async getConversations(roomId = null) {
    const q = roomId ? `?room_id=${encodeURIComponent(roomId)}` : '';
    return this.get(`/api/chat/conversations${q}`);
  },

  async createConversation(title = 'New Chat', roomId = null) {
    const q = new URLSearchParams({ title });
    if (roomId) q.append('room_id', roomId);
    return this.post(`/api/chat/conversations?${q.toString()}`, {});
  },

  async getConversation(convId) {
    return this.get(`/api/chat/conversations/${convId}`);
  },

  async deleteConversation(convId) {
    return this.delete(`/api/chat/conversations/${convId}`);
  },

  // --------------------------------------------------------------------------
  // Settings & Health
  // --------------------------------------------------------------------------
  async getSettings() {
    return this.get('/api/settings');
  },

  async updateSettings(settings) {
    return this.post('/api/settings', settings);
  },

  async getHealth() {
    return this.get('/api/health');
  },

  // --------------------------------------------------------------------------
  // Two-Tier Memory System (Global & User, Short-Term & Long-Term)
  // --------------------------------------------------------------------------
  async listMemories(params = {}) {
    const q = new URLSearchParams(params).toString();
    return this.get(`/api/memory${q ? '?' + q : ''}`);
  },

  async createMemory(payload) {
    return this.post('/api/memory', payload);
  },

  async getMemoryStats() {
    return this.get('/api/memory/stats');
  },

  async revaluateMemories(payload = {}) {
    return this.post('/api/memory/revaluate', payload);
  },

  async deleteMemory(memoryId) {
    return this.delete(`/api/memory/${memoryId}`);
  },

  async pruneExpiredMemories() {
    return this.delete('/api/memory/prune');
  },
};

window.API = API;
try {
  API.syncCookieToken();
} catch (e) {
  console.warn('Could not sync cookie token:', e);
}

