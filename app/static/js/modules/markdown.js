/**
 * Rich Markdown Parsing, Response Classifier & Assistant Message Rendering
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;
  const markdownCache = new Map();

  function renderMarkdown(rawText, citations = []) {
    if (!rawText) return '';

    // Cache lookup for fast historical re-rendering
    const cacheKey = rawText.length < 800 ? `${rawText}:${citations.length}` : null;
    if (cacheKey && markdownCache.has(cacheKey)) {
      return markdownCache.get(cacheKey);
    }

    let text = rawText;

    // 1. Extract and preserve code blocks
    const codeBlocks = [];
    text = text.replace(/```([a-zA-Z0-9_-]*)\r?\n([\s\S]*?)```/g, (match, lang, code) => {
      const placeholder = `@@RAGCODEBLOCK${codeBlocks.length}@@`;
      codeBlocks.push({
        lang: lang.trim() || 'plaintext',
        code: code.trimEnd(),
      });
      return placeholder;
    });

    // 2. Extract and preserve markdown tables
    const tables = [];
    text = text.replace(/((?:^|\n)\|[^\n]+\|\r?\n\|[-:\s|]+\|\r?\n(?:\|[^\n]+\|\r?\n?)+)/g, (match) => {
      const placeholder = `@@RAGTABLEBLOCK${tables.length}@@`;
      tables.push(match.trim());
      return '\n\n' + placeholder + '\n\n';
    });

    // 3. Escape HTML
    text = RAG.utils.escapeHtml(text);

    // 4. Blockquotes
    text = text.replace(/^>\s?(.*)$/gm, '<blockquote>$1</blockquote>');

    // 5. Headings
    text = text.replace(/^#### (.*$)/gm, '<h4>$1</h4>');
    text = text.replace(/^### (.*$)/gm, '<h3>$1</h3>');
    text = text.replace(/^## (.*$)/gm, '<h2>$1</h2>');
    text = text.replace(/^# (.*$)/gm, '<h1>$1</h1>');

    // 6. Bold & Italic
    text = text.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
    text = text.replace(/__(.*?)__/g, '<strong>$1</strong>');
    text = text.replace(/_(.*?)_/g, '<em>$1</em>');

    // 7. Inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 8. Citations inline reference: [1], [2], etc.
    if (citations && citations.length > 0) {
      const regKey = 'cite_' + Math.floor(Math.random() * 1000000);
      global.__citationsRegistry = global.__citationsRegistry || {};
      global.__citationsRegistry[regKey] = { citations, query: RAG.state.lastUserQuery || '' };

      text = text.replace(/\[(\d+)\]/g, (match, num) => {
        const idx = parseInt(num, 10) - 1;
        const citation = citations[idx];
        if (citation) {
          return `<span class="inline-citation" onclick="window.openEvidenceModal('${regKey}', ${idx})" title="${RAG.utils.escapeHtml(citation.filename)} (Page ${citation.page || 1} - Click to inspect evidence proof)">[${num}]</span>`;
        }
        return match;
      });
    }

    // 9. Unordered Lists
    text = text.replace(/^[-*•]\s+(.*)$/gm, '<li>$1</li>');
    text = text.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

    // 10. Ordered Lists
    text = text.replace(/^\d+\.\s+(.*)$/gm, '<li class="ol-item">$1</li>');
    text = text.replace(/(<li class="ol-item">.*<\/li>\n?)+/g, '<ol>$&</ol>');

    // 11. Links
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    // 12. Paragraphs & Line Breaks
    text = text.replace(/\n\n+/g, '</p><p>');
    text = `<p>${text}</p>`;
    text = text.replace(/<p><\/p>/g, '');
    text = text.replace(/<p>(<h[1-4]>)/g, '$1');
    text = text.replace(/(<\/h[1-4]>)<\/p>/g, '$1');
    text = text.replace(/<p>(<ul|<ol|<blockquote>)/g, '$1');
    text = text.replace(/(<\/ul>|<\/ol>|<\/blockquote>)<\/p>/g, '$1');

    // 13. Reinsert Tables
    tables.forEach((rawTable, i) => {
      const rows = rawTable.split('\n').filter((r) => r.trim().startsWith('|'));
      if (rows.length >= 2) {
        const headerCells = rows[0].split('|').slice(1, -1).map((c) => c.trim());
        const bodyRows = rows.slice(2).map((r) => r.split('|').slice(1, -1).map((c) => c.trim()));

        let tableHtml = `<div class="markdown-table-wrapper"><table class="markdown-table"><thead><tr>`;
        headerCells.forEach((h) => {
          tableHtml += `<th>${RAG.utils.escapeHtml(h)}</th>`;
        });
        tableHtml += `</tr></thead><tbody>`;

        bodyRows.forEach((row) => {
          tableHtml += `<tr>`;
          row.forEach((cell) => {
            tableHtml += `<td>${RAG.utils.escapeHtml(cell)}</td>`;
          });
          tableHtml += `</tr>`;
        });
        tableHtml += `</tbody></table></div>`;

        text = text.replace(`@@RAGTABLEBLOCK${i}@@`, tableHtml);
      } else {
        text = text.replace(`@@RAGTABLEBLOCK${i}@@`, `<pre>${RAG.utils.escapeHtml(rawTable)}</pre>`);
      }
    });

    // 14. Reinsert Code Blocks with Copy Button
    codeBlocks.forEach((item, i) => {
      const codeId = `code-block-${Date.now()}-${i}-${Math.floor(Math.random() * 1000)}`;
      const escapedCode = RAG.utils.escapeHtml(item.code);
      const blockHtml = `
        <div class="code-block-container" id="${codeId}">
          <div class="code-block-header">
            <span class="code-lang-label">
              <span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:var(--accent-primary);"></span>
              ${RAG.utils.escapeHtml(item.lang)}
            </span>
            <button class="code-copy-btn" onclick="window.copyCode(this, '${codeId}')" title="Copy code snippet">
              <span class="copy-icon">📋</span>
              <span class="copy-label">Copy</span>
            </button>
          </div>
          <pre><code class="language-${RAG.utils.escapeHtml(item.lang)}">${escapedCode}</code></pre>
        </div>
      `;
      text = text.replace(`@@RAGCODEBLOCK${i}@@`, blockHtml);
    });

    if (cacheKey) {
      if (markdownCache.size > 200) {
        const oldestKey = markdownCache.keys().next().value;
        markdownCache.delete(oldestKey);
      }
      markdownCache.set(cacheKey, text);
    }

    return text;
  }

  function classifyResponse(content, meta = {}, citations = []) {
    let responseType = meta.response_type;

    if (!responseType) {
      if (meta.intent === 'greeting') {
        responseType = 'greeting';
      } else if (
        content.includes('do not contain sufficient information') ||
        content.includes('Please upload relevant files') ||
        meta.is_relevant === false
      ) {
        responseType = 'insufficient_info';
      } else if (citations && citations.length > 0) {
        responseType = 'grounded';
      } else {
        responseType = 'general';
      }
    }

    const configs = {
      grounded: {
        badgeClass: 'grounded',
        badgeIcon: '🛡️',
        badgeText: 'GROUNDED ANSWER',
        avatarIcon: '🛡️',
        avatarClass: 'grounded',
      },
      insufficient_info: {
        badgeClass: 'insufficient',
        badgeIcon: '⚠️',
        badgeText: 'INSUFFICIENT INFORMATION',
        avatarIcon: '⚠️',
        avatarClass: 'insufficient_info',
      },
      greeting: {
        badgeClass: 'greeting',
        badgeIcon: '✨',
        badgeText: 'CONVERSATIONAL GREETING',
        avatarIcon: '✨',
        avatarClass: 'greeting',
      },
      general: {
        badgeClass: 'general',
        badgeIcon: '💡',
        badgeText: 'GENERAL SYNTHESIS',
        avatarIcon: '⚡',
        avatarClass: '',
      },
      error: {
        badgeClass: 'error',
        badgeIcon: '❌',
        badgeText: 'EXECUTION ERROR',
        avatarIcon: '❌',
        avatarClass: 'insufficient_info',
      },
    };

    return configs[responseType] || configs.general;
  }

  function renderAssistantMessage({ content, citations = [], meta = {}, timestamp }) {
    const config = classifyResponse(content, meta, citations);
    const messagesContainer = document.getElementById('messages-container');
    if (!messagesContainer) return;

    const row = document.createElement('div');
    row.className = 'message-row assistant';

    let badgesHtml = `
      <div class="message-meta-header">
        <span class="response-type-pill ${config.badgeClass}">
          <span>${config.badgeIcon}</span>
          <span>${config.badgeText}</span>
        </span>
    `;

    if (meta.provider && meta.model) {
      badgesHtml += `
        <span class="response-model-tag">
          ${RAG.utils.escapeHtml(meta.provider.toUpperCase())} / ${RAG.utils.escapeHtml(meta.model)}
        </span>
      `;
    }

    if (meta.retrieval_retry_count && meta.retrieval_retry_count > 0) {
      badgesHtml += `
        <span class="meta-tag-pill" title="Query was automatically rewritten and re-retrieved">
          🔄 ${meta.retrieval_retry_count} retries
        </span>
      `;
    }

    badgesHtml += `</div>`;

    let citationsHtml = '';
    if (citations && citations.length > 0) {
      const regKey = 'pill_cite_' + Math.floor(Math.random() * 1000000);
      global.__citationsRegistry = global.__citationsRegistry || {};
      global.__citationsRegistry[regKey] = { citations, query: RAG.state.lastUserQuery || '' };

      citationsHtml = `
        <div class="citations-section">
          <div class="citations-header">
            <span class="citations-header-title">
              <span class="citations-header-icon">📚</span>
              <span>Verified Sources</span>
            </span>
            <span class="citations-count-pill">${citations.length} references</span>
          </div>
          <div class="citation-pills-row">
            ${citations
              .map((c, i) => {
                const matchPct = Math.round((c.relevance_score || 0) * 100);
                const pageNum = c.page || 1;
                return `
                  <div class="citation-pill" onclick="window.openEvidenceModal('${regKey}', ${i})" role="button" tabindex="0" title="Click to inspect realtime document evidence on page ${pageNum}">
                    <span class="citation-pill-index">[${i + 1}]</span>
                    <span class="citation-pill-name">${RAG.utils.escapeHtml(c.filename)}</span>
                    <span class="citation-pill-page">p.${pageNum}</span>
                    ${matchPct > 0 ? `<span class="citation-pill-score">${matchPct}%</span>` : ''}
                    <span class="citation-pill-arrow">↗</span>
                  </div>
                `;
              })
              .join('')}
          </div>
        </div>
      `;
    }

    const htmlBody = renderMarkdown(content, citations);

    row.innerHTML = `
      <div class="message-avatar ${config.avatarClass}">${config.avatarIcon}</div>
      <div class="message-content-wrapper">
        ${badgesHtml}
        <div class="message-bubble">
          <div class="bubble-markdown">${htmlBody}</div>
          ${citationsHtml}
        </div>
        <div class="message-actions-bar">
          <div class="msg-action-time">${timestamp ? new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}</div>
          <div class="msg-action-buttons">
            <button class="msg-action-btn" onclick="window.copyAnswer(this)" title="Copy entire response">
              <span class="btn-icon">📋</span>
              <span>Copy</span>
            </button>
            <button class="msg-action-btn" onclick="window.retryLastQuery()" title="Regenerate this response">
              <span class="btn-icon">🔄</span>
              <span>Retry</span>
            </button>
          </div>
        </div>
      </div>
    `;

    messagesContainer.appendChild(row);
    RAG.utils.scheduleScrollToBottom(true);
  }

  // Register on RAG.markdown
  RAG.markdown = {
    renderMarkdown,
    classifyResponse,
    renderAssistantMessage,
  };

  // Expose globally
  global.renderMarkdown = renderMarkdown;
  global.classifyResponse = classifyResponse;
  global.renderAssistantMessage = renderAssistantMessage;
})(window);
