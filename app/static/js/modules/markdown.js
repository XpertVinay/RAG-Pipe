/**
 * Rich Markdown Parsing, Response Classifier & Assistant Message Rendering
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  // Cache for non-streaming rendered content
  const markdownCache = new Map();
  const lastIframeContent = new Map();
  let iframeUpdateTimeout = null;
  let streamRaf = null;
  let latestStreamJob = null;

  // Active tab state for interactive preview blocks
  window.__activePreviewTabs = window.__activePreviewTabs || {};

  /**
   * Normalize language strings and select the appropriate specific renderer
   * Handles compound/pipe delimiters like ```bash|```python|```html or ```bash|python|html
   */
  function normalizeLanguage(langStr = '') {
    const raw = String(langStr || '').trim().toLowerCase();
    // Clean backticks, pipes, slashes, spaces
    const cleaned = raw.replace(/^[`\s|]+|[`\s|]+$/g, '');

    // 1. Browser Previewable Languages (HTML, SVG, XML)
    if (cleaned.includes('html') || cleaned.includes('htm') || cleaned.includes('xhtml') || cleaned.includes('svg')) {
      return {
        lang: 'html',
        displayName: 'HTML (Browser Preview)',
        renderer: 'browser_preview',
        langColor: '#38bdf8',
        icon: '🌐',
      };
    }

    // 2. Terminal / Shell Commands (Bash, Sh, Zsh, Shell)
    if (
      cleaned.includes('bash') ||
      cleaned.includes('shell') ||
      cleaned.includes('zsh') ||
      cleaned.includes('sh') ||
      cleaned.includes('terminal') ||
      cleaned.includes('console') ||
      cleaned.includes('cmd') ||
      cleaned.includes('powershell')
    ) {
      return {
        lang: 'bash',
        displayName: 'Bash / Terminal',
        renderer: 'terminal',
        langColor: '#10b981',
        icon: '⚡',
      };
    }

    // 3. Python Execution Block
    if (cleaned.includes('python') || cleaned.includes('py')) {
      return {
        lang: 'python',
        displayName: 'Python 3',
        renderer: 'python',
        langColor: '#818cf8',
        icon: '🐍',
      };
    }

    // 4. JavaScript / TypeScript
    if (cleaned.includes('javascript') || cleaned.includes('js') || cleaned.includes('jsx')) {
      return {
        lang: 'javascript',
        displayName: 'JavaScript',
        renderer: 'javascript',
        langColor: '#facc15',
        icon: '⚡',
      };
    }
    if (cleaned.includes('typescript') || cleaned.includes('ts') || cleaned.includes('tsx')) {
      return {
        lang: 'typescript',
        displayName: 'TypeScript',
        renderer: 'javascript',
        langColor: '#60a5fa',
        icon: '🔷',
      };
    }

    // 5. JSON
    if (cleaned.includes('json')) {
      return {
        lang: 'json',
        displayName: 'JSON',
        renderer: 'json',
        langColor: '#fb923c',
        icon: '{ }',
      };
    }

    // 6. CSS
    if (cleaned.includes('css') || cleaned.includes('scss') || cleaned.includes('less')) {
      return {
        lang: 'css',
        displayName: 'CSS',
        renderer: 'css',
        langColor: '#38bdf8',
        icon: '🎨',
      };
    }

    // 7. SQL
    if (cleaned.includes('sql')) {
      return {
        lang: 'sql',
        displayName: 'SQL',
        renderer: 'sql',
        langColor: '#a78bfa',
        icon: '🗄️',
      };
    }

    return {
      lang: cleaned || 'plaintext',
      displayName: (cleaned || 'Code').toUpperCase(),
      renderer: 'generic',
      langColor: 'var(--accent-primary)',
      icon: '📄',
    };
  }

  /**
   * Fast, secure regex syntax highlighter for styled blocks
   */
  function highlightSyntax(rawCode = '', renderer = 'generic') {
    const escaped = RAG.utils.escapeHtml(rawCode);

    if (renderer === 'terminal') {
      const lines = escaped.split('\n');
      return lines
        .map((line) => {
          const trimmed = line.trim();
          if (trimmed.startsWith('#')) {
            return `<span class="terminal-comment">${line}</span>`;
          }
          if (trimmed.length > 0) {
            return `<span class="terminal-prompt">$</span> <span class="terminal-cmd">${line}</span>`;
          }
          return line;
        })
        .join('\n');
    }

    if (renderer === 'python') {
      let code = escaped;
      // Comments
      code = code.replace(/(#[^\n]*)/g, '<span class="token-comment">$1</span>');
      // Strings
      code = code.replace(/(&quot;.*?&quot;|&#39;.*?&#39;|""".*?""")/g, '<span class="token-string">$1</span>');
      // Decorators
      code = code.replace(/(@[a-zA-Z0-9_\.]+)/g, '<span class="token-decorator">$1</span>');
      // Keywords
      code = code.replace(
        /\b(def|class|return|import|from|as|if|elif|else|while|for|in|try|except|finally|with|async|await|yield|pass|break|continue|lambda|and|or|not|is|None|True|False)\b/g,
        '<span class="token-keyword">$1</span>'
      );
      // Builtins
      code = code.replace(
        /\b(print|len|range|str|int|float|list|dict|set|tuple|bool|super|type|open|enumerate|zip|map|filter)\b/g,
        '<span class="token-builtin">$1</span>'
      );
      // Numbers
      code = code.replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="token-number">$1</span>');
      return code;
    }

    if (renderer === 'browser_preview' || renderer === 'html') {
      let code = escaped;
      // Comments
      code = code.replace(/(&lt;!--[\s\S]*?--&gt;)/g, '<span class="html-comment">$1</span>');
      // Tags
      code = code.replace(/(&lt;\/?[a-zA-Z0-9\-]+)/g, '<span class="html-tag">$1</span>');
      // Attributes & values
      code = code.replace(
        /([a-zA-Z\-:]+)=(&quot;.*?&quot;|&#39;.*?&#39;)/g,
        '<span class="html-attr">$1</span>=<span class="html-val">$2</span>'
      );
      return code;
    }

    if (renderer === 'javascript') {
      let code = escaped;
      // Comments
      code = code.replace(/(\/\/[^\n]*|\/\*[\s\S]*?\*\/)/g, '<span class="token-comment">$1</span>');
      // Strings
      code = code.replace(/(&quot;.*?&quot;|&#39;.*?&#39;|`.*?`)/g, '<span class="token-string">$1</span>');
      // Keywords
      code = code.replace(
        /\b(const|let|var|function|return|import|export|from|default|class|extends|new|if|else|for|while|do|switch|case|break|continue|try|catch|finally|throw|async|await|yield|typeof|instanceof|void|null|undefined|true|false)\b/g,
        '<span class="token-keyword">$1</span>'
      );
      // Numbers
      code = code.replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="token-number">$1</span>');
      return code;
    }

    return escaped;
  }

  /**
   * Build complete sandbox iframe document with modern default styling
   */
  function buildIframeDocument(code = '') {
    const trimmed = (code || '').trim();
    if (trimmed.toLowerCase().includes('<html') || trimmed.toLowerCase().includes('<!doctype')) {
      return trimmed;
    }
    return `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      margin: 16px;
      color: #1e293b;
      background: #ffffff;
      line-height: 1.5;
    }
    * { box-sizing: border-box; }
  </style>
</head>
<body>
  ${trimmed}
</body>
</html>`;
  }

  /**
   * Update iframe preview safely without unnecessary reloads
   */
  function updateIframePreview(iframe, code, force = false) {
    if (!iframe) return;
    const currentHash = (iframe.id || 'preview') + '::' + code;
    if (!force && lastIframeContent.get(iframe.id) === currentHash) {
      return;
    }
    lastIframeContent.set(iframe.id, currentHash);
    iframe.srcdoc = buildIframeDocument(code);
  }

  /**
   * Initialize all browser preview iframes in a container
   */
  function initBrowserPreviewIframes(containerEl, debounce = false) {
    if (!containerEl) return;
    const iframes = containerEl.querySelectorAll('.browser-preview-iframe');
    if (!iframes.length) return;

    const doUpdate = () => {
      iframes.forEach((iframe) => {
        const blockId = iframe.id.replace('-iframe', '');
        const blockEl = document.getElementById(blockId);
        if (!blockEl) return;
        const codeEl = blockEl.querySelector('.browser-code-viewport code') || blockEl.querySelector('code');
        if (codeEl) {
          updateIframePreview(iframe, codeEl.textContent);
        }
      });
    };

    if (debounce) {
      if (iframeUpdateTimeout) clearTimeout(iframeUpdateTimeout);
      iframeUpdateTimeout = setTimeout(doUpdate, 100);
    } else {
      doUpdate();
    }
  }

  /**
   * Toggle between Browser Preview and Source Code viewports
   */
  function togglePreviewTab(btn, blockId, tab) {
    window.__activePreviewTabs = window.__activePreviewTabs || {};
    window.__activePreviewTabs[blockId] = tab;

    const container = document.getElementById(blockId);
    if (!container) return;

    const previewView = container.querySelector('.browser-preview-viewport');
    const codeView = container.querySelector('.browser-code-viewport');
    const addressBar = container.querySelector('.browser-address-bar');
    const allTabBtns = container.querySelectorAll('.preview-tab-btn');

    allTabBtns.forEach((b) => {
      b.classList.toggle('active', b.dataset.tab === tab);
    });

    if (tab === 'preview') {
      if (previewView) previewView.style.display = 'block';
      if (addressBar) addressBar.style.display = 'flex';
      if (codeView) codeView.style.display = 'none';
      const iframe = container.querySelector('.browser-preview-iframe');
      const codeEl = container.querySelector('.browser-code-viewport code');
      if (iframe && codeEl) {
        updateIframePreview(iframe, codeEl.textContent, true);
      }
    } else {
      if (previewView) previewView.style.display = 'none';
      if (addressBar) addressBar.style.display = 'none';
      if (codeView) codeView.style.display = 'block';
    }
  }

  /**
   * Open live preview in a standalone browser window/tab
   */
  function openInNewTab(blockId) {
    const container = document.getElementById(blockId);
    if (!container) return;
    const codeEl = container.querySelector('.browser-code-viewport code') || container.querySelector('code');
    if (!codeEl) return;
    const html = codeEl.textContent || '';
    const fullHtml = buildIframeDocument(html);
    const blob = new Blob([fullHtml], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    window.open(url, '_blank');
  }

  /**
   * Force refresh of a specific browser preview iframe
   */
  function refreshPreview(blockId) {
    const container = document.getElementById(blockId);
    if (!container) return;
    const iframe = container.querySelector('.browser-preview-iframe');
    const codeEl = container.querySelector('.browser-code-viewport code') || container.querySelector('code');
    if (iframe && codeEl) {
      updateIframePreview(iframe, codeEl.textContent, true);
    }
  }

  /**
   * Render a specific code block HTML according to its specialized renderer
   */
  function renderCodeBlockHtml(block, options = {}) {
    const { langInfo, code, isStreaming, blockId } = block;
    const activeTab = window.__activePreviewTabs?.[blockId] || 'preview';
    const highlighted = highlightSyntax(code, langInfo.renderer);
    const streamCursorHtml = isStreaming ? '<span class="streaming-cursor"></span>' : '';

    // SPECIFIC RENDERER 1: Browser Preview for HTML
    if (langInfo.renderer === 'browser_preview') {
      return `
        <div class="code-block-container browser-preview-container" id="${blockId}">
          <div class="code-block-header browser-preview-header">
            <div class="preview-header-left">
              <div class="window-controls">
                <span class="win-dot dot-red"></span>
                <span class="win-dot dot-yellow"></span>
                <span class="win-dot dot-green"></span>
              </div>
              <div class="preview-title-badge">
                <span class="preview-icon">🌐</span>
                <span class="preview-lang-text">HTML — BROWSER PREVIEW</span>
              </div>
              ${isStreaming ? '<span class="live-stream-badge"><span class="live-dot"></span> LIVE RENDERING</span>' : '<span class="live-stream-badge compiled"><span class="live-dot-static"></span> PREVIEW READY</span>'}
            </div>
            <div class="preview-header-actions">
              <div class="preview-tab-pills" role="tablist">
                <button type="button" class="preview-tab-btn ${activeTab === 'preview' ? 'active' : ''}" data-tab="preview" onclick="window.togglePreviewTab(this, '${blockId}', 'preview')" title="Switch to rendered browser view">
                  <span>🖥️ Browser Preview</span>
                </button>
                <button type="button" class="preview-tab-btn ${activeTab === 'code' ? 'active' : ''}" data-tab="code" onclick="window.togglePreviewTab(this, '${blockId}', 'code')" title="Switch to HTML source code view">
                  <span>&lt;/&gt; HTML Source</span>
                </button>
              </div>
              <button type="button" class="code-action-btn" onclick="window.openInNewTab('${blockId}')" title="Open preview in new browser window">
                <span>↗️ Popout</span>
              </button>
              <button type="button" class="code-copy-btn" onclick="window.copyCode(this, '${blockId}')" title="Copy HTML code">
                <span class="copy-icon">📋</span>
                <span class="copy-label">Copy</span>
              </button>
            </div>
          </div>

          <!-- Browser Address Mockup -->
          <div class="browser-address-bar" style="${activeTab === 'code' ? 'display: none;' : ''}">
            <div class="browser-nav-icons">
              <button type="button" class="nav-btn" title="Back" disabled>‹</button>
              <button type="button" class="nav-btn" title="Forward" disabled>›</button>
              <button type="button" class="nav-btn nav-reload" onclick="window.refreshPreview('${blockId}')" title="Reload preview">↻</button>
            </div>
            <div class="browser-url-pill">
              <span class="url-lock">🔒</span>
              <span class="url-text">preview://localhost:3000/index.html</span>
            </div>
            <div class="browser-viewport-badge">Live DOM Sandbox</div>
          </div>

          <!-- Tab 1: Live Browser Preview -->
          <div class="browser-preview-viewport" id="${blockId}-preview" style="${activeTab === 'code' ? 'display: none;' : ''}">
            <iframe class="browser-preview-iframe" id="${blockId}-iframe" sandbox="allow-scripts allow-modals" loading="lazy" title="Live HTML Preview"></iframe>
          </div>

          <!-- Tab 2: Monospace HTML Code -->
          <div class="browser-code-viewport" id="${blockId}-code" style="${activeTab === 'preview' ? 'display: none;' : ''}">
            <pre><code class="language-html">${highlighted}${streamCursorHtml}</code></pre>
          </div>
        </div>
      `;
    }

    // SPECIFIC RENDERER 2: Terminal / Bash Commands
    if (langInfo.renderer === 'terminal') {
      return `
        <div class="code-block-container terminal-block-container" id="${blockId}">
          <div class="code-block-header terminal-header">
            <div class="terminal-header-left">
              <div class="window-controls">
                <span class="win-dot dot-red"></span>
                <span class="win-dot dot-yellow"></span>
                <span class="win-dot dot-green"></span>
              </div>
              <div class="terminal-title-badge">
                <span class="terminal-icon">⚡</span>
                <span class="terminal-lang-text">BASH / TERMINAL</span>
              </div>
              ${isStreaming ? '<span class="live-stream-badge terminal-stream"><span class="live-dot"></span> STREAMING</span>' : ''}
            </div>
            <div class="terminal-header-actions">
              <button type="button" class="code-copy-btn" onclick="window.copyCode(this, '${blockId}')" title="Copy command snippet">
                <span class="copy-icon">📋</span>
                <span class="copy-label">Copy</span>
              </button>
            </div>
          </div>
          <pre class="terminal-pre"><code class="language-bash terminal-code">${highlighted}${streamCursorHtml}</code></pre>
        </div>
      `;
    }

    // SPECIFIC RENDERER 3: Python Script Block
    if (langInfo.renderer === 'python') {
      return `
        <div class="code-block-container python-block-container" id="${blockId}">
          <div class="code-block-header python-header">
            <div class="python-header-left">
              <div class="window-controls">
                <span class="win-dot dot-red"></span>
                <span class="win-dot dot-yellow"></span>
                <span class="win-dot dot-green"></span>
              </div>
              <div class="python-title-badge">
                <span class="python-icon">🐍</span>
                <span class="python-lang-text">PYTHON 3</span>
              </div>
              ${isStreaming ? '<span class="live-stream-badge python-stream"><span class="live-dot"></span> RUNNING</span>' : ''}
            </div>
            <div class="python-header-actions">
              <button type="button" class="code-copy-btn" onclick="window.copyCode(this, '${blockId}')" title="Copy python script">
                <span class="copy-icon">📋</span>
                <span class="copy-label">Copy</span>
              </button>
            </div>
          </div>
          <pre class="python-pre"><code class="language-python">${highlighted}${streamCursorHtml}</code></pre>
        </div>
      `;
    }

    // Standard / Generic Code Block
    return `
      <div class="code-block-container standard-code-container" id="${blockId}">
        <div class="code-block-header standard-code-header">
          <div class="code-header-left">
            <div class="window-controls">
              <span class="win-dot dot-red"></span>
              <span class="win-dot dot-yellow"></span>
              <span class="win-dot dot-green"></span>
            </div>
            <span class="code-lang-label">
              <span class="lang-color-dot" style="background:${langInfo.langColor || 'var(--accent-primary)'};"></span>
              ${RAG.utils.escapeHtml(langInfo.displayName)}
            </span>
            ${isStreaming ? '<span class="live-stream-badge"><span class="live-dot"></span> STREAMING</span>' : ''}
          </div>
          <div class="code-header-actions">
            <button type="button" class="code-copy-btn" onclick="window.copyCode(this, '${blockId}')" title="Copy code snippet">
              <span class="copy-icon">📋</span>
              <span class="copy-label">Copy</span>
            </button>
          </div>
        </div>
        <pre><code class="language-${RAG.utils.escapeHtml(langInfo.lang)}">${highlighted}${streamCursorHtml}</code></pre>
      </div>
    `;
  }

  /**
   * Split raw text into alternating markdown text and code blocks.
   * Handles opening delimiters like ```bash, ```python, ```html, pipe syntax,
   * closing delimiters (``` or ```lang), and actively open blocks during streaming.
   */
  function parseContentBlocks(rawText = '', isStreamingActive = false) {
    const blocks = [];
    let pos = 0;
    const len = rawText.length;
    let blockCounter = 0;

    while (pos < len) {
      // Find opening fence ```
      const openMatch = rawText.slice(pos).match(/(?:^|\n)```([a-zA-Z0-9_\-#+|`]*)[ \t]*(?:\r?\n|$)/);
      if (!openMatch) {
        // No more code fences, rest is markdown
        const textSegment = rawText.slice(pos);
        if (textSegment) {
          blocks.push({ type: 'markdown', content: textSegment });
        }
        break;
      }

      const matchRelativeIdx = openMatch.index;
      const actualOpenIdx = pos + matchRelativeIdx + (openMatch[0].startsWith('\n') ? 1 : 0);

      // Text before opening fence
      if (actualOpenIdx > pos) {
        const textBefore = rawText.slice(pos, actualOpenIdx);
        if (textBefore) {
          blocks.push({ type: 'markdown', content: textBefore });
        }
      }

      const rawLang = openMatch[1] || '';
      const langInfo = normalizeLanguage(rawLang);
      const codeStartPos = pos + matchRelativeIdx + openMatch[0].length;
      blockCounter++;
      const blockId = `code-block-${Date.now()}-${blockCounter}`;

      // Search for closing fence: either ``` or ```lang or ```pipe
      const restText = rawText.slice(codeStartPos);
      const closeMatch = restText.match(/(?:^|\n)```([a-zA-Z0-9_\-#+|`]*)[ \t]*(?:\r?\n|$)/);

      if (closeMatch) {
        // Closed block
        const codeEndRelativeIdx = closeMatch.index + (closeMatch[0].startsWith('\n') ? 1 : 0);
        const code = restText.slice(0, codeEndRelativeIdx);
        blocks.push({
          type: 'code',
          langInfo,
          code,
          isStreaming: false,
          blockId,
        });
        pos = codeStartPos + closeMatch.index + closeMatch[0].length;
      } else {
        // Unclosed block - delimiter has hit during active stream!
        const code = restText;
        blocks.push({
          type: 'code',
          langInfo,
          code,
          isStreaming: isStreamingActive,
          blockId,
        });
        pos = len; // Consumed to end
      }
    }

    return blocks;
  }

  /**
   * Render non-code markdown segments (headings, bold, lists, tables, citations)
   */
  function renderMarkdownSegment(rawText, citations = []) {
    if (!rawText) return '';
    let text = rawText;

    // 1. Extract and preserve tables
    const tables = [];
    text = text.replace(/((?:^|\n)\|[^\n]+\|\r?\n\|[-:\s|]+\|\r?\n(?:\|[^\n]+\|\r?\n?)+)/g, (match) => {
      const placeholder = `@@RAGTABLEBLOCK${tables.length}@@`;
      tables.push(match.trim());
      return '\n\n' + placeholder + '\n\n';
    });

    // 2. Escape HTML
    text = RAG.utils.escapeHtml(text);

    // 3. Blockquotes
    text = text.replace(/^>\s?(.*)$/gm, '<blockquote>$1</blockquote>');

    // 4. Headings
    text = text.replace(/^#### (.*$)/gm, '<h4>$1</h4>');
    text = text.replace(/^### (.*$)/gm, '<h3>$1</h3>');
    text = text.replace(/^## (.*$)/gm, '<h2>$1</h2>');
    text = text.replace(/^# (.*$)/gm, '<h1>$1</h1>');

    // 5. Bold & Italic
    text = text.replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>');
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
    text = text.replace(/__(.*?)__/g, '<strong>$1</strong>');
    text = text.replace(/_(.*?)_/g, '<em>$1</em>');

    // 6. Inline code
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');

    // 7. Citations inline reference: [1], [2], etc.
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

    // 8. Unordered Lists
    text = text.replace(/^[-*•]\s+(.*)$/gm, '<li>$1</li>');
    text = text.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

    // 9. Ordered Lists
    text = text.replace(/^\d+\.\s+(.*)$/gm, '<li class="ol-item">$1</li>');
    text = text.replace(/(<li class="ol-item">.*<\/li>\n?)+/g, '<ol>$&</ol>');

    // 10. Links
    text = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

    // 11. Paragraphs & Line Breaks
    text = text.replace(/\n\n+/g, '</p><p>');
    text = `<p>${text}</p>`;
    text = text.replace(/<p><\/p>/g, '');
    text = text.replace(/<p>(<h[1-4]>)/g, '$1');
    text = text.replace(/(<\/h[1-4]>)<\/p>/g, '$1');
    text = text.replace(/<p>(<ul|<ol|<blockquote>)/g, '$1');
    text = text.replace(/(<\/ul>|<\/ol>|<\/blockquote>)<\/p>/g, '$1');

    // 12. Reinsert Tables
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

    return text;
  }

  /**
   * Main Markdown Renderer with Delimiter & Streaming Block Support
   */
  function renderMarkdown(rawText, citations = [], options = {}) {
    if (!rawText) return '';
    const isStreaming = Boolean(options.isStreaming);

    // Fast cache for completed messages
    const cacheKey = !isStreaming && rawText.length < 800 ? `${rawText}:${citations.length}` : null;
    if (cacheKey && markdownCache.has(cacheKey)) {
      return markdownCache.get(cacheKey);
    }

    const parsedBlocks = parseContentBlocks(rawText, isStreaming);
    let htmlOutput = '';

    parsedBlocks.forEach((block) => {
      if (block.type === 'code') {
        htmlOutput += renderCodeBlockHtml(block, options);
      } else {
        htmlOutput += renderMarkdownSegment(block.content, citations);
      }
    });

    if (cacheKey) {
      if (markdownCache.size > 200) {
        const oldestKey = markdownCache.keys().next().value;
        markdownCache.delete(oldestKey);
      }
      markdownCache.set(cacheKey, htmlOutput);
    }

    return htmlOutput;
  }

  /**
   * Progressive stream renderer called on every SSE token.
   * Uses requestAnimationFrame and debounced iframe updates for 60fps rendering.
   */
  function renderStreaming(containerEl, accumulatedContent, options = {}) {
    if (!containerEl) return;
    latestStreamJob = { containerEl, accumulatedContent, options };

    if (!streamRaf) {
      streamRaf = requestAnimationFrame(() => {
        streamRaf = null;
        if (!latestStreamJob) return;
        const { containerEl: target, accumulatedContent: content, options: opt } = latestStreamJob;
        const html = renderMarkdown(content, opt.citations || [], { isStreaming: true });
        target.innerHTML = html;
        initBrowserPreviewIframes(target, true);
        if (RAG.utils?.scheduleScrollToBottom) {
          RAG.utils.scheduleScrollToBottom();
        }
      });
    }
  }

  function classifyResponse(content, meta = {}, citations = []) {
    let responseType = meta.response_type;

    if (!responseType) {
      if (meta.guardrail_blocked || (content && (content.includes('GUARDRAIL REFUSAL') || content.includes('SAFETY & ETHICAL GUARDRAIL')))) {
        responseType = 'guardrail_violation';
      } else if (meta.is_app_creation || meta.intent === 'app_creation' || (content && content.includes('Application Blueprint'))) {
        responseType = 'app_creation';
      } else if (meta.intent === 'greeting') {
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
      app_creation: {
        badgeClass: 'grounded',
        badgeIcon: '🚀',
        badgeText: 'APPLICATION BLUEPRINT & PROJECT REQUEST',
        avatarIcon: '🚀',
        avatarClass: 'grounded',
      },
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
      guardrail_violation: {
        badgeClass: 'guardrail',
        badgeIcon: '⛔',
        badgeText: 'POLICY VIOLATION & ACCESS CAUTION',
        avatarIcon: '⛔',
        avatarClass: 'guardrail',
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
        <div class="citations-section" aria-label="Verified evidence sources">
          <div class="citations-header">
            <div class="citations-header-title">
              <span class="citations-header-shield" aria-hidden="true">
                <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.8">
                  <path d="M8 1.5l5.5 2v4.5c0 3.5-2.5 6-5.5 7-3-1-5.5-3.5-5.5-7V3.5l5.5-2z" fill="rgba(16, 185, 129, 0.15)" stroke="#10b981"/>
                  <path d="M5.5 8l2 2 3.5-3.5" stroke="#34d399" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
              </span>
              <span class="citations-title-text">VERIFIED SOURCES</span>
              <span class="citations-live-badge">GROUNDED PROOF</span>
            </div>
            <div class="citations-header-meta">
              <span class="citations-count-pill">${citations.length} ${citations.length === 1 ? 'REFERENCE' : 'REFERENCES'}</span>
            </div>
          </div>
          <div class="citation-pills-row">
            ${citations
              .map((c, i) => {
                const matchPct = Math.round((c.relevance_score || 0) * 100);
                const pageNum = c.page || 1;
                const filename = c.filename || 'Source Document';
                const escapedName = RAG.utils.escapeHtml(filename);
                const fileExt = (filename.split('.').pop() || 'doc').toLowerCase();

                let fileIconSvg = `
                  <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" class="doc-icon-svg">
                    <path d="M3 2.5a1 1 0 011-1h5.5l4 4V13.5a1 1 0 01-1 1H4a1 1 0 01-1-1v-11z" fill="rgba(99, 102, 241, 0.12)" stroke="#818cf8"/>
                    <path d="M9 1.5v4h4" stroke="#818cf8"/>
                  </svg>
                `;
                if (fileExt === 'pdf') {
                  fileIconSvg = `
                    <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" class="doc-icon-svg icon-pdf">
                      <path d="M3 2.5a1 1 0 011-1h5.5l4 4V13.5a1 1 0 01-1 1H4a1 1 0 01-1-1v-11z" fill="rgba(244, 63, 94, 0.15)" stroke="#fb7185"/>
                      <path d="M9 1.5v4h4" stroke="#fb7185"/>
                    </svg>
                  `;
                } else if (fileExt === 'csv' || fileExt === 'xlsx' || fileExt === 'xls') {
                  fileIconSvg = `
                    <svg viewBox="0 0 16 16" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" class="doc-icon-svg icon-data">
                      <path d="M3 2.5a1 1 0 011-1h5.5l4 4V13.5a1 1 0 01-1 1H4a1 1 0 01-1-1v-11z" fill="rgba(16, 185, 129, 0.15)" stroke="#34d399"/>
                      <path d="M9 1.5v4h4" stroke="#34d399"/>
                    </svg>
                  `;
                }

                let scoreClass = 'score-high';
                if (matchPct < 50) scoreClass = 'score-low';
                else if (matchPct < 70) scoreClass = 'score-mid';

                let excerptSnippet = '';
                if (c.excerpt && c.excerpt.trim()) {
                  let cleaned = c.excerpt.replace(/\s+/g, ' ').trim();
                  if (cleaned.length > 135) cleaned = cleaned.substring(0, 132) + '...';
                  excerptSnippet = `
                    <div class="citation-card-excerpt" title="${RAG.utils.escapeHtml(c.excerpt)}">
                      <span class="excerpt-quote" aria-hidden="true">“</span>
                      <span class="excerpt-text">${RAG.utils.escapeHtml(cleaned)}</span>
                    </div>
                  `;
                }

                return `
                  <div class="citation-pill" onclick="window.openEvidenceModal('${regKey}', ${i})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();window.openEvidenceModal('${regKey}', ${i});}" role="button" tabindex="0" title="Click to inspect realtime document evidence on page ${pageNum} (${escapedName})">
                    <div class="citation-pill-main">
                      <div class="citation-pill-left">
                        <span class="citation-pill-index">[${i + 1}]</span>
                        <span class="citation-pill-icon">${fileIconSvg}</span>
                        <span class="citation-pill-name" title="${escapedName}">${escapedName}</span>
                      </div>
                      <div class="citation-pill-right">
                        <span class="citation-pill-page" title="Source document page ${pageNum}">
                          <svg viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.8" class="page-mini-icon">
                            <rect x="3" y="2" width="10" height="12" rx="1.5"/>
                            <line x1="6" y1="5" x2="10" y2="5"/>
                            <line x1="6" y1="8" x2="10" y2="8"/>
                          </svg>
                          <span>p.${pageNum}</span>
                        </span>
                        ${matchPct > 0 ? `
                          <span class="citation-pill-score ${scoreClass}" title="Semantic relevance match score">
                            <span class="score-pulse-dot"></span>
                            <span>${matchPct}%</span>
                          </span>
                        ` : ''}
                        <span class="citation-pill-arrow" aria-hidden="true">
                          <svg viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M4.5 11.5L11.5 4.5M11.5 4.5H6.5M11.5 4.5V9.5" stroke-linecap="round" stroke-linejoin="round"/>
                          </svg>
                        </span>
                      </div>
                    </div>
                    ${excerptSnippet}
                  </div>
                `;
              })
              .join('')}
          </div>
      `;
    }

    let visualizationHtml = '';
    const vis = meta?.visualization;
    if (vis && (vis.image_base64 || vis.code || vis.error)) {
      const visId = 'vis_' + Math.floor(Math.random() * 1000000);
      const isSuccess = vis.success !== false && (vis.image_base64 || !vis.error);
      const statusBadge = isSuccess
        ? `<span class="vis-badge-success" style="font-size: 11px; padding: 2px 7px; border-radius: 4px; background: rgba(16, 185, 129, 0.15); color: #059669; font-weight: 600;">✓ Python Executed</span>`
        : `<span class="vis-badge-error" style="font-size: 11px; padding: 2px 7px; border-radius: 4px; background: rgba(239, 68, 68, 0.15); color: #dc2626; font-weight: 600;">Execution Warning</span>`;

      const timeStr = vis.execution_time_ms ? `<span style="font-size: 11px; color: var(--text-muted, #64748b);">(${vis.execution_time_ms}ms)</span>` : '';

      visualizationHtml = `
        <div class="visualization-card" style="margin-top: 14px; border: 1px solid var(--border-color, #e2e8f0); border-radius: 10px; overflow: hidden; background: var(--bg-surface, #ffffff);">
          <div class="vis-card-header" style="padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color, #e2e8f0); background: rgba(99, 102, 241, 0.04);">
            <div style="display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 12px; color: #4338ca;">
              <span>📈</span>
              <span>VISUAL REPRESENTATION</span>
              ${statusBadge}
              ${timeStr}
            </div>
            ${vis.code ? `
              <button class="vis-toggle-btn" onclick="const d = document.getElementById('${visId}_code'); if(d) d.style.display = d.style.display === 'none' ? 'block' : 'none';" style="background: none; border: 1px solid #cbd5e1; border-radius: 5px; padding: 2px 8px; font-size: 11px; color: #475569; cursor: pointer;">
                Toggle Code
              </button>
            ` : ''}
          </div>
          ${vis.image_base64 ? `
            <div class="vis-image-container" style="padding: 12px; text-align: center; background: #ffffff;">
              <img src="${vis.image_base64}" alt="Generated Visualization" style="max-width: 100%; height: auto; border-radius: 6px; box-shadow: 0 2px 5px rgba(0,0,0,0.06);" />
            </div>
          ` : ''}
          ${vis.error && !vis.image_base64 ? `
            <div class="vis-error-msg" style="padding: 10px 12px; font-size: 12px; color: #b91c1c; background: #fef2f2;">
              ⚠️ Sandbox execution notice: ${RAG.utils.escapeHtml(vis.error)}
            </div>
          ` : ''}
          ${vis.code ? `
            <div id="${visId}_code" class="vis-code-drawer" style="display: none; border-top: 1px solid #e2e8f0; padding: 10px 12px; background: #0f172a; color: #f8fafc; font-family: monospace; font-size: 11.5px; max-height: 220px; overflow-y: auto; text-align: left;">
              <pre style="margin: 0; white-space: pre-wrap;"><code>${RAG.utils.escapeHtml(vis.code)}</code></pre>
            </div>
          ` : ''}
        </div>
      `;
    }

    let cautionBannerHtml = '';
    const isGuardrail = meta?.guardrail_blocked || meta?.response_type === 'guardrail_violation' || (content && (content.includes('GUARDRAIL REFUSAL') || content.includes('SAFETY & ETHICAL GUARDRAIL')));
    if (isGuardrail) {
      const strikeText = meta?.strike_count ? `(Strike ${meta.strike_count}/${meta.max_strikes || 3})` : '';
      const restrictedBadge = meta?.is_restricted ? '<span class="guardrail-pill-restricted">ACCESS SUSPENDED</span>' : '';
      const authorityBadge = meta?.reported_to_authority ? '<span class="guardrail-pill-reported">REPORTED TO AUTHORITIES</span>' : '<span class="guardrail-pill-monitored">FLAGGED FOR REVIEW</span>';

      cautionBannerHtml = `
        <div class="guardrail-caution-box" role="alert">
          <div class="guardrail-caution-header">
            <div class="guardrail-caution-header-left">
              <span class="guardrail-caution-icon">⚠️</span>
              <span class="guardrail-caution-title">SECURITY & COMPLIANCE ENFORCEMENT ${strikeText}</span>
            </div>
            <div class="guardrail-caution-badges">
              ${restrictedBadge}
              ${authorityBadge}
            </div>
          </div>
          <div class="guardrail-caution-body">
            <strong>CRITICAL POLICY CAUTION:</strong>
            Queries soliciting <em>illegal</em>, <em>dangerous</em>, or <em>unethical</em> instructions are strictly blocked.
            <strong>Continuous or repeated similar questionnaire submissions will restrict your platform access and be formally reported to the appropriate security administrators and legal authorities.</strong>
          </div>
        </div>
      `;
    }

    let appRequestCardHtml = '';
    const isAppCreation = meta?.is_app_creation || meta?.response_type === 'app_creation' || (meta?.intent === 'app_creation') || (content && content.includes('Application Blueprint'));
    if (isAppCreation) {
      const cardId = 'app_card_' + Math.floor(Math.random() * 1000000);
      const appName = meta?.suggested_app_name || 'Custom Application Project';
      const currentUser = (global.API && global.API.getCurrentUser) ? global.API.getCurrentUser() : null;
      const clientName = currentUser ? (currentUser.full_name || currentUser.username || '') : '';
      const email = currentUser ? (currentUser.email || '') : '';

      appRequestCardHtml = `
        <div class="app-request-card" id="${cardId}">
          <div class="app-request-header">
            <div class="app-request-title-wrap">
              <span class="app-request-icon">🚀</span>
              <span class="app-request-title">Application Development Project Request</span>
            </div>
            <span class="app-request-badge">Projects Table Synchronized</span>
          </div>
          <div class="app-request-desc">
            Your application request has been formulated from the LLM prompt. Specify your contact details and preferred channel (<strong>Google Meet</strong>, <strong>Microsoft Teams</strong>, or <strong>Zoom</strong>) to register this request into the <strong>projects</strong> table and initiate a consultation call accompanied by the full conversation transcripts.
          </div>
          
          <div class="app-request-form-grid">
            <div class="app-req-field-group">
              <label>Application / Project Name</label>
              <input type="text" class="app-req-name-input" value="${RAG.utils.escapeHtml(appName)}" placeholder="Project Name">
            </div>
            <div class="app-req-field-group">
              <label>Your Full Name</label>
              <input type="text" class="app-req-client-name-input" value="${RAG.utils.escapeHtml(clientName)}" placeholder="e.g. John Doe">
            </div>
            <div class="app-req-field-group">
              <label>Email Address</label>
              <input type="email" class="app-req-email-input" value="${RAG.utils.escapeHtml(email)}" placeholder="e.g. john@company.com">
            </div>
            <div class="app-req-field-group">
              <label>Phone Number</label>
              <input type="tel" class="app-req-phone-input" placeholder="+1 (555) 019-2834">
            </div>
            <div class="app-req-field-group" style="grid-column: 1 / -1;">
              <label>Communication Channel</label>
              <select class="app-req-channel-select">
                <option value="Gmeet">🟢 Google Meet (Gmeet)</option>
                <option value="Teams">🟣 Microsoft Teams</option>
                <option value="Zoom">🔵 Zoom</option>
                <option value="others">⚪ Others (Phone / Slack / Direct)</option>
              </select>
            </div>
          </div>

          <div class="app-request-actions">
            <div style="font-size: 0.72rem; color: #94a3b8; display: flex; align-items: center; gap: 5px;">
              <span>📜</span>
              <span>Full conversation transcripts will be attached automatically to the call.</span>
            </div>
            <button type="button" class="app-req-btn-submit" onclick="window.submitAppProjectRequest('${cardId}')">
              <span>🚀 Submit Project Request &amp; Prepare Call</span>
            </button>
          </div>

          <div class="app-req-status-area" style="display: none; margin-top: 10px;"></div>
        </div>
      `;
    }

    const htmlBody = renderMarkdown(content, citations);

    row.innerHTML = `
      <div class="message-avatar ${config.avatarClass}">${config.avatarIcon}</div>
      <div class="message-content-wrapper">
        ${badgesHtml}
        <div class="message-bubble ${isGuardrail ? 'guardrail-bubble' : ''}">
          ${cautionBannerHtml}
          <div class="bubble-markdown">${htmlBody}</div>
          ${visualizationHtml}
          ${citationsHtml}
          ${appRequestCardHtml}
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
    // Initialize any browser preview iframes
    initBrowserPreviewIframes(row, false);

    // Respect user scroll intent: do not force scroll down if the user has scrolled up to read initial content
    if (!RAG.utils?.getIsUserScrolledUp?.()) {
      RAG.utils.scheduleScrollToBottom(true);
    }
  }

  /**
   * Finalize an active streaming row in-place without reloading iframes or causing flicker
   */
  function finalizeStreaming(assistantRow, { content, citations = [], meta = {}, timestamp }) {
    if (!assistantRow) return;

    // 1. Remove streaming status badge
    const statusBanner = assistantRow.querySelector('.streaming-status');
    if (statusBanner) statusBanner.remove();

    // 2. Classify response and update avatar icon
    const config = classifyResponse(content, meta, citations);
    const avatarEl = assistantRow.querySelector('.message-avatar');
    if (avatarEl) {
      avatarEl.className = `message-avatar ${config.avatarClass}`;
      avatarEl.textContent = config.avatarIcon;
    }

    const contentWrapper = assistantRow.querySelector('.message-content-wrapper');
    const bubble = assistantRow.querySelector('.message-bubble');
    if (!contentWrapper || !bubble) return;

    // 3. Badges Header
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

    const existingMeta = contentWrapper.querySelector('.message-meta-header');
    if (existingMeta) existingMeta.remove();
    contentWrapper.insertAdjacentHTML('afterbegin', badgesHtml);

    // 4. Final markdown render (closes any open streaming blocks and finalizes code styles)
    const finalHtml = renderMarkdown(content, citations, { isStreaming: false });
    const bubbleMarkdown = bubble.querySelector('.bubble-markdown') || bubble;
    bubbleMarkdown.innerHTML = finalHtml;
    bubbleMarkdown.classList.remove('streaming-markdown');

    const cursor = bubble.querySelector('.streaming-cursor');
    if (cursor) cursor.remove();

    // 5. Initialize all browser preview iframes in final state
    initBrowserPreviewIframes(bubbleMarkdown, false);

    // 6. Action Bar
    let existingActions = contentWrapper.querySelector('.message-actions-bar');
    if (!existingActions) {
      const actionsBarHtml = `
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
      `;
      contentWrapper.insertAdjacentHTML('beforeend', actionsBarHtml);
    }
  }

  // Register on RAG.markdown
  RAG.markdown = {
    renderMarkdown,
    renderStreaming,
    finalizeStreaming,
    classifyResponse,
    renderAssistantMessage,
    updateIframePreview,
    initBrowserPreviewIframes,
    buildIframeDocument,
    togglePreviewTab,
    openInNewTab,
    refreshPreview,
  };

  // Expose globally
  global.renderMarkdown = renderMarkdown;
  global.renderStreaming = renderStreaming;
  global.finalizeStreaming = finalizeStreaming;
  global.classifyResponse = classifyResponse;
  global.renderAssistantMessage = renderAssistantMessage;
  global.togglePreviewTab = togglePreviewTab;
  global.openInNewTab = openInNewTab;
  global.refreshPreview = refreshPreview;
})(window);
