/**
 * Server-Sent Events (SSE) Stream Reader with Abort Controller support
 */
class SSEClient {
  constructor() {
    this.abortController = null;
  }

  async streamQuery({
    message,
    conversationId,
    documentIds,
    provider,
    model,
    temperature,
    topK,
    onStatus,
    onToken,
    onCitations,
    onDone,
    onError,
  }) {
    if (this.abortController) {
      this.abortController.abort();
    }
    this.abortController = new AbortController();

    try {
      const response = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
        },
        body: JSON.stringify({
          message,
          conversation_id: conversationId,
          document_ids: documentIds && documentIds.length > 0 ? documentIds : null,
          provider: provider || null,
          model: model || null,
          temperature: temperature || 0.2,
          top_k: topK || 4,
        }),
        signal: this.abortController.signal,
      });

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`Server returned HTTP ${response.status}: ${errorText}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop(); // Keep partial frame in buffer

        for (const rawEvent of events) {
          if (!rawEvent.trim()) continue;

          let eventType = 'message';
          let eventData = '';

          const lines = rawEvent.split('\n');
          for (const line of lines) {
            if (line.startsWith('event:')) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith('data:')) {
              eventData = line.slice(5).trim();
            }
          }

          if (!eventData) continue;

          try {
            const parsed = JSON.parse(eventData);

            if (eventType === 'status' && onStatus) {
              onStatus(parsed.message || parsed);
            } else if (eventType === 'token' && onToken) {
              onToken(parsed.token || '');
            } else if (eventType === 'citations' && onCitations) {
              onCitations(parsed.citations || []);
            } else if (eventType === 'done' && onDone) {
              onDone(parsed);
            } else if (eventType === 'error' && onError) {
              onError(parsed.message || 'Stream error occurred.');
            }
          } catch (e) {
            console.error('Failed to parse SSE JSON payload:', eventData, e);
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        console.log('RAG streaming request was aborted by client.');
      } else {
        console.error('SSE streaming error:', err);
        if (onError) onError(err.message || 'Connection lost.');
      }
    } finally {
      this.abortController = null;
    }
  }

  abort() {
    if (this.abortController) {
      this.abortController.abort();
      this.abortController = null;
    }
  }
}

window.SSEClient = SSEClient;
