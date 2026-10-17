/**
 * Production RAG Agent Client API Service
 */
const API = {
  async get(url) {
    const res = await fetch(url);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.message || 'API request failed');
    }
    return res.json();
  },

  async post(url, data) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.message || 'API request failed');
    }
    return res.json();
  },

  async delete(url) {
    const res = await fetch(url, { method: 'DELETE' });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.message || 'API request failed');
    }
    return res.json();
  },

  // Document Endpoints
  async getDocuments(status = null) {
    const q = status ? `?status=${encodeURIComponent(status)}` : '';
    return this.get(`/api/documents${q}`);
  },

  async uploadFiles(fileList) {
    const formData = new FormData();
    for (const file of fileList) {
      formData.append('files', file);
    }
    const res = await fetch('/api/documents/upload', {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      throw new Error(err.message || 'Upload failed');
    }
    return res.json();
  },

  async deleteDocument(docId) {
    return this.delete(`/api/documents/${docId}`);
  },

  async reprocessDocument(docId) {
    return this.post(`/api/documents/${docId}/reprocess`, {});
  },

  // Chat & Conversation Endpoints
  async getConversations() {
    return this.get('/api/chat/conversations');
  },

  async createConversation(title = 'New Chat') {
    return this.post(`/api/chat/conversations?title=${encodeURIComponent(title)}`, {});
  },

  async getConversation(convId) {
    return this.get(`/api/chat/conversations/${convId}`);
  },

  async deleteConversation(convId) {
    return this.delete(`/api/chat/conversations/${convId}`);
  },

  // Settings & Health
  async getSettings() {
    return this.get('/api/settings');
  },

  async updateSettings(settings) {
    return this.post('/api/settings', settings);
  },

  async getHealth() {
    return this.get('/api/health');
  },
};

window.API = API;
