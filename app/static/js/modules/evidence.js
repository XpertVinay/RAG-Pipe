/**
 * Realtime Proof Evidence Inspector Modal & Document Landing Controller
 */
(function (global) {
  'use strict';

  global.RAG = global.RAG || {};
  const RAG = global.RAG;

  let activeEvidenceState = {
    docId: null,
    filename: '',
    currentPage: 1,
    totalPages: 1,
    chunkId: null,
    query: '',
    viewMode: 'split', // 'split' | 'highlights' | 'document'
    allCitations: [],
    activeCitationIndex: 0,
  };

  function updateEvidenceViewMode(mode) {
    const citationModalBody = document.getElementById('citation-modal-body');
    const evidenceTabSplit = document.getElementById('evidence-tab-split');
    const evidenceTabHighlights = document.getElementById('evidence-tab-highlights');
    const evidenceTabDocument = document.getElementById('evidence-tab-document');

    activeEvidenceState.viewMode = mode;
    if (citationModalBody) {
      citationModalBody.className = `evidence-modal-body view-${mode}`;
    }
    [evidenceTabSplit, evidenceTabHighlights, evidenceTabDocument].forEach((btn) => {
      if (btn) btn.classList.remove('active');
    });
    if (mode === 'split' && evidenceTabSplit) evidenceTabSplit.classList.add('active');
    if (mode === 'highlights' && evidenceTabHighlights) evidenceTabHighlights.classList.add('active');
    if (mode === 'document' && evidenceTabDocument) evidenceTabDocument.classList.add('active');
  }

  async function fetchAndRenderEvidence(docId, page, chunkId, query) {
    const citationModalBody = document.getElementById('citation-modal-body');
    const evidencePageDisplay = document.getElementById('evidence-page-display');
    const evidencePrevPageBtn = document.getElementById('evidence-prev-page-btn');
    const evidenceNextPageBtn = document.getElementById('evidence-next-page-btn');
    const evidenceOpenFileBtn = document.getElementById('evidence-open-file-btn');
    const evidenceMetaText = document.getElementById('evidence-meta-text');

    if (!docId || !citationModalBody) return;
    citationModalBody.innerHTML = `
      <div class="evidence-loading-spinner">
        <span>⚡</span>
        <span>Loading document evidence from page ${page}...</span>
      </div>
    `;

    try {
      const data = await API.getDocumentEvidence(docId, page, chunkId, query);
      activeEvidenceState.currentPage = data.page;
      activeEvidenceState.totalPages = data.total_pages || 1;

      if (evidencePageDisplay) {
        evidencePageDisplay.textContent = `Page ${data.page} / ${data.total_pages || 1}`;
      }
      if (evidencePrevPageBtn) {
        evidencePrevPageBtn.disabled = data.page <= 1;
      }
      if (evidenceNextPageBtn) {
        evidenceNextPageBtn.disabled = data.page >= data.total_pages;
      }

      const token = API.getAccessToken();
      const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
      const baseFileUrl = `/api/documents/${data.document_id}/file${tokenParam}#page=${data.page || 1}`;
      const livePdfUrl = `${baseFileUrl}&view=FitH`;

      if (evidenceOpenFileBtn) {
        evidenceOpenFileBtn.href = baseFileUrl;
      }
      if (evidenceMetaText) {
        evidenceMetaText.textContent = `Page ${data.page} of ${data.total_pages || 1} • Chunk ${data.chunk_id || 'N/A'}`;
      }

      const matchedLines = (data.highlight_lines || []).filter((l) => l.is_match);
      const matchCount = matchedLines.length;

      const linesHtml = (data.highlight_lines || [])
        .map((l) => {
          const matchClass = l.is_match ? 'matched-line' : '';
          let displayText = RAG.utils.escapeHtml(l.text || ' ');

          if (l.is_match && query) {
            const tokens = query.toLowerCase().match(/\w{4,}/g) || [];
            tokens.forEach((tok) => {
              const regex = new RegExp(`(${tok})`, 'gi');
              displayText = displayText.replace(regex, '<mark>$1</mark>');
            });
          }

          return `
            <div class="doc-line-row ${matchClass}" id="doc-line-${l.line_number}">
              <span class="doc-line-num">${l.line_number}</span>
              <span class="doc-line-text">${displayText}</span>
            </div>
          `;
        })
        .join('');

      const leftPaneHtml = `
        <div class="evidence-lines-pane">
          <div class="evidence-pane-banner">
            <div class="evidence-pane-banner-left">
              <span>🎯</span>
              <span>${matchCount > 0 ? `${matchCount} matched line(s) on Page ${data.page}` : `Page ${data.page} Source Lines`}</span>
            </div>
            ${
              matchCount > 0
                ? `<button class="evidence-jump-btn" onclick="document.querySelector('.matched-line')?.scrollIntoView({ behavior: 'smooth', block: 'center' })">⚡ Jump to Match</button>`
                : ''
            }
          </div>
          <div class="evidence-lines-scroll" id="evidence-lines-container">
            ${linesHtml || '<div style="padding: 20px; color: var(--text-muted);">No text extracted on this page.</div>'}
          </div>
        </div>
      `;

      const isPdf = (data.file_type || '').toLowerCase().includes('pdf') || data.filename.toLowerCase().endsWith('.pdf');
      const rightPaneHtml = `
        <div class="evidence-doc-pane">
          ${
            isPdf
              ? `<iframe src="${livePdfUrl}" class="evidence-pdf-frame" title="Live Document Proof"></iframe>`
              : `
              <div class="evidence-fallback-message">
                <span style="font-size: 2rem;">📄</span>
                <strong>Document Preview: ${RAG.utils.escapeHtml(data.filename)}</strong>
                <p style="font-size: 0.8rem; max-width: 320px;">Use the Highlighted Source Lines pane on the left for exact matched line attribution.</p>
                <a href="${baseFileUrl}" target="_blank" class="btn btn-primary" style="font-size: 0.78rem;">Open Full Document</a>
              </div>
            `
          }
        </div>
      `;

      citationModalBody.innerHTML = leftPaneHtml + rightPaneHtml;
      updateEvidenceViewMode(activeEvidenceState.viewMode);

      setTimeout(() => {
        const firstMatch = citationModalBody.querySelector('.matched-line');
        if (firstMatch) {
          firstMatch.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      }, 150);
    } catch (err) {
      citationModalBody.innerHTML = `
        <div style="padding: 30px; text-align: center; color: var(--accent-danger);">
          <p>Failed to load realtime document evidence: ${RAG.utils.escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }

  function renderEvidenceInspector(c, allCitations, query, activeIndex = 0) {
    const citationModal = document.getElementById('citation-modal');
    const evidenceFilename = document.getElementById('evidence-filename');
    const evidenceScoreBadge = document.getElementById('evidence-score-badge');
    const evidenceMetaText = document.getElementById('evidence-meta-text');
    const evidenceOpenFileBtn = document.getElementById('evidence-open-file-btn');
    const evidenceCitationsBar = document.getElementById('evidence-citations-bar');
    const evidenceCitationsList = document.getElementById('evidence-citations-list');

    activeEvidenceState.docId = c.document_id;
    activeEvidenceState.filename = c.filename;
    activeEvidenceState.currentPage = c.page || 1;
    activeEvidenceState.chunkId = c.chunk_id;
    activeEvidenceState.query = query || RAG.state.lastUserQuery || '';
    activeEvidenceState.allCitations = Array.isArray(allCitations) && allCitations.length > 0 ? allCitations : [c];
    activeEvidenceState.activeCitationIndex = activeIndex;

    if (evidenceFilename) evidenceFilename.textContent = c.filename;
    if (evidenceScoreBadge) {
      const matchPct = Math.round((c.relevance_score || 0) * 100);
      evidenceScoreBadge.textContent = `${matchPct}% Match`;
    }
    if (evidenceMetaText) {
      evidenceMetaText.textContent = `Page ${c.page || 1} • Chunk ${c.chunk_id || 'N/A'}`;
    }
    if (evidenceOpenFileBtn) {
      const token = API.getAccessToken();
      const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
      evidenceOpenFileBtn.href = `/api/documents/${c.document_id}/file${tokenParam}#page=${c.page || 1}`;
    }

    if (evidenceCitationsBar && evidenceCitationsList) {
      if (activeEvidenceState.allCitations.length > 1) {
        evidenceCitationsBar.style.display = 'flex';
        evidenceCitationsList.innerHTML = activeEvidenceState.allCitations
          .map((item, idx) => {
            const isActive = idx === activeIndex ? 'active' : '';
            return `
              <button class="evidence-nav-chip ${isActive}" onclick="window.renderEvidenceInspector(window.__activeEvidenceList[${idx}], window.__activeEvidenceList, '${RAG.utils.escapeHtml(activeEvidenceState.query).replace(/'/g, "\\'")}', ${idx})">
                <span>[${idx + 1}]</span>
                <span>${RAG.utils.escapeHtml(item.filename)}</span>
                <span>p.${item.page || 1}</span>
              </button>
            `;
          })
          .join('');
        global.__activeEvidenceList = activeEvidenceState.allCitations;
      } else {
        evidenceCitationsBar.style.display = 'none';
      }
    }

    if (window.innerWidth <= 768 && activeEvidenceState.viewMode === 'split') {
      updateEvidenceViewMode('highlights');
    }

    citationModal?.classList.add('active');
    fetchAndRenderEvidence(
      activeEvidenceState.docId,
      activeEvidenceState.currentPage,
      activeEvidenceState.chunkId,
      activeEvidenceState.query
    );
  }

  function openEvidenceModal(registryKey, citationIndex) {
    const entry = (global.__citationsRegistry || {})[registryKey];
    if (!entry || !entry.citations || !entry.citations[citationIndex]) {
      return;
    }
    const c = entry.citations[citationIndex];
    renderEvidenceInspector(c, entry.citations, entry.query, citationIndex);
  }

  function showCitationModal(c) {
    renderEvidenceInspector(c, [c], RAG.state.lastUserQuery || '', 0);
  }

  function initEvidenceListeners() {
    const evidenceTabSplit = document.getElementById('evidence-tab-split');
    const evidenceTabHighlights = document.getElementById('evidence-tab-highlights');
    const evidenceTabDocument = document.getElementById('evidence-tab-document');
    const evidencePrevPageBtn = document.getElementById('evidence-prev-page-btn');
    const evidenceNextPageBtn = document.getElementById('evidence-next-page-btn');
    const closeCitationBtn = document.getElementById('close-citation-btn');
    const citationModal = document.getElementById('citation-modal');

    evidenceTabSplit?.addEventListener('click', () => updateEvidenceViewMode('split'));
    evidenceTabHighlights?.addEventListener('click', () => updateEvidenceViewMode('highlights'));
    evidenceTabDocument?.addEventListener('click', () => updateEvidenceViewMode('document'));

    evidencePrevPageBtn?.addEventListener('click', () => {
      if (activeEvidenceState.currentPage > 1) {
        activeEvidenceState.currentPage--;
        fetchAndRenderEvidence(
          activeEvidenceState.docId,
          activeEvidenceState.currentPage,
          activeEvidenceState.chunkId,
          activeEvidenceState.query
        );
      }
    });

    evidenceNextPageBtn?.addEventListener('click', () => {
      if (activeEvidenceState.currentPage < activeEvidenceState.totalPages) {
        activeEvidenceState.currentPage++;
        fetchAndRenderEvidence(
          activeEvidenceState.docId,
          activeEvidenceState.currentPage,
          activeEvidenceState.chunkId,
          activeEvidenceState.query
        );
      }
    });

    closeCitationBtn?.addEventListener('click', () => citationModal?.classList.remove('active'));
  }

  RAG.evidence = {
    fetchAndRenderEvidence,
    renderEvidenceInspector,
    openEvidenceModal,
    showCitationModal,
    updateEvidenceViewMode,
    init: initEvidenceListeners,
  };

  global.renderEvidenceInspector = renderEvidenceInspector;
  global.openEvidenceModal = openEvidenceModal;
  global.showCitationModal = showCitationModal;
})(window);
