/**
 * Enterprise Audit Trail & Business Risk Visualization Module
 */
(function (global) {
  'use strict';

  const AuditRisk = {
    currentPage: 0,
    pageSize: 25,
    totalRecords: 0,

    init: function () {
      this.bindEvents();
    },

    bindEvents: function () {
      const modal = document.getElementById('audit-risk-modal');
      const openBtn = document.getElementById('open-audit-risk-btn');
      const closeBtn = document.getElementById('close-audit-risk-modal-btn');

      if (openBtn) {
        openBtn.addEventListener('click', () => {
          this.openModal();
        });
      }

      if (closeBtn && modal) {
        closeBtn.addEventListener('click', () => {
          modal.classList.remove('active');
        });
      }

      // Close on backdrop click
      if (modal) {
        modal.addEventListener('click', (e) => {
          if (e.target === modal) {
            modal.classList.remove('active');
          }
        });
      }

      // Tab Switching
      const tabBtns = document.querySelectorAll('.audit-tab-btn');
      tabBtns.forEach((btn) => {
        btn.addEventListener('click', () => {
          tabBtns.forEach((b) => b.classList.remove('active'));
          btn.classList.add('active');

          const targetId = btn.getAttribute('data-target');
          document.querySelectorAll('.audit-tab-panel').forEach((p) => p.classList.remove('active'));
          const targetPanel = document.getElementById(targetId);
          if (targetPanel) targetPanel.classList.add('active');

          if (targetId === 'panel-risk-overview') {
            this.loadRiskMetrics();
          } else if (targetId === 'panel-risk-logs') {
            this.loadAuditLogs();
          } else if (targetId === 'panel-risk-backups') {
            this.loadBackups();
          }
        });
      });

      // Refresh Button
      const refreshBtn = document.getElementById('refresh-risk-metrics-btn');
      if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
          this.loadRiskMetrics();
        });
      }

      // Filter Buttons
      const applyFiltersBtn = document.getElementById('audit-apply-filters-btn');
      if (applyFiltersBtn) {
        applyFiltersBtn.addEventListener('click', () => {
          this.currentPage = 0;
          this.loadAuditLogs();
        });
      }

      // Pagination
      const prevBtn = document.getElementById('audit-prev-page-btn');
      const nextBtn = document.getElementById('audit-next-page-btn');
      if (prevBtn) {
        prevBtn.addEventListener('click', () => {
          if (this.currentPage > 0) {
            this.currentPage--;
            this.loadAuditLogs();
          }
        });
      }
      if (nextBtn) {
        nextBtn.addEventListener('click', () => {
          if ((this.currentPage + 1) * this.pageSize < this.totalRecords) {
            this.currentPage++;
            this.loadAuditLogs();
          }
        });
      }

      // Save Compliance Remark Button
      const saveRemarkBtn = document.getElementById('save-compliance-remark-btn');
      if (saveRemarkBtn) {
        saveRemarkBtn.addEventListener('click', () => {
          this.saveComplianceRemark();
        });
      }

      // Backup creation button
      const createBackupBtn = document.getElementById('create-audit-backup-btn');
      if (createBackupBtn) {
        createBackupBtn.addEventListener('click', () => {
          this.triggerBackup();
        });
      }

      // Verify Chain Integrity button
      const verifyBtn = document.getElementById('verify-chain-integrity-btn');
      if (verifyBtn) {
        verifyBtn.addEventListener('click', () => {
          this.verifyIntegrity();
        });
      }

      // Export CSV Button
      const exportBtn = document.getElementById('audit-export-csv-btn');
      if (exportBtn) {
        exportBtn.addEventListener('click', () => {
          const token = API.getAccessToken();
          window.open(`/api/v1/audit/export?export_format=csv&token=${encodeURIComponent(token || '')}`, '_blank');
        });
      }
    },

    openModal: function () {
      const modal = document.getElementById('audit-risk-modal');
      if (modal) {
        modal.classList.add('active');
        this.loadRiskMetrics();
      }
    },

    loadRiskMetrics: async function () {
      try {
        const metrics = await API.getRiskDashboard(24);
        this.renderRiskMetrics(metrics);
      } catch (err) {
        console.error('Failed to load risk dashboard metrics:', err);
      }
    },

    renderRiskMetrics: function (data) {
      if (!data) return;

      const score = data.risk_index ?? 5.0;
      const level = data.risk_level ?? 'LOW';

      // Header Risk Pill
      const headerPill = document.getElementById('header-risk-pill');
      if (headerPill) {
        headerPill.className = `risk-chip ${level.toLowerCase()}`;
        headerPill.textContent = `RISK: ${score} (${level})`;
      }

      // Gauge Circle
      const gauge = document.getElementById('risk-gauge-circle');
      if (gauge) {
        gauge.textContent = Math.round(score);
        let color = '#10b981';
        if (level === 'MEDIUM') color = '#f59e0b';
        else if (level === 'HIGH') color = '#ef4444';
        else if (level === 'CRITICAL') color = '#e11d48';

        gauge.style.borderColor = color;
        gauge.style.color = color;
        gauge.style.boxShadow = `0 0 16px ${color}33`;
      }

      // Level Tag & Summary
      const tag = document.getElementById('risk-level-tag');
      if (tag) {
        tag.className = `risk-chip ${level.toLowerCase()}`;
        tag.textContent = `${level} RISK`;
      }

      const summaryText = document.getElementById('risk-summary-text');
      if (summaryText) summaryText.textContent = data.risk_summary;

      const lastUpdated = document.getElementById('risk-last-updated');
      if (lastUpdated) lastUpdated.textContent = `Evaluated: ${new Date().toLocaleTimeString()}`;

      // Fluctuation Cards
      const breakdown = data.domain_breakdown || {};
      const deltas = data.fluctuations_1h_vs_24h || {};

      // Card 1: Core Logic
      const coreData = breakdown.core_logic || {};
      const coreRateEl = document.getElementById('card-core-rate');
      if (coreRateEl) coreRateEl.textContent = `${coreData.failure_rate ?? 0.0}%`;
      const coreDeltaEl = document.getElementById('card-core-delta');
      if (coreDeltaEl) {
        const d = deltas.core_logic_delta ?? 0.0;
        coreDeltaEl.className = `fluctuation-delta ${d > 0 ? 'delta-positive' : 'delta-neutral'}`;
        coreDeltaEl.textContent = `• 1h trend: ${d > 0 ? '+' : ''}${d}% delta`;
      }

      // Card 2: New Logic
      const newData = breakdown.new_logic || {};
      const newRateEl = document.getElementById('card-new-rate');
      if (newRateEl) newRateEl.textContent = `${newData.failure_rate ?? 0.0}%`;
      const newDeltaEl = document.getElementById('card-new-delta');
      if (newDeltaEl) {
        const d = deltas.new_logic_delta ?? 0.0;
        newDeltaEl.className = `fluctuation-delta ${d > 0 ? 'delta-positive' : 'delta-neutral'}`;
        newDeltaEl.textContent = `• 1h trend: ${d > 0 ? '+' : ''}${d}% delta`;
      }

      // Card 3: Third Party
      const tpData = breakdown.third_party_failure || {};
      const tpRateEl = document.getElementById('card-tp-rate');
      if (tpRateEl) tpRateEl.textContent = `${tpData.failure_rate ?? 0.0}%`;
      const tpDeltaEl = document.getElementById('card-tp-delta');
      if (tpDeltaEl) {
        const d = deltas.third_party_delta ?? 0.0;
        tpDeltaEl.className = `fluctuation-delta ${d > 0 ? 'delta-positive' : 'delta-neutral'}`;
        tpDeltaEl.textContent = `• 1h trend: ${d > 0 ? '+' : ''}${d}% delta`;
      }

      // Card 4: Exceptions
      const excData = breakdown.exception_handling || {};
      const excCountEl = document.getElementById('card-exc-count');
      if (excCountEl) excCountEl.textContent = excData.failures ?? 0;
      const excDeltaEl = document.getElementById('card-exc-delta');
      if (excDeltaEl) {
        excDeltaEl.textContent = `• Total logged: ${excData.total ?? 0}`;
      }

      // Recommendations List
      const recList = document.getElementById('risk-recommendations-list');
      if (recList && data.recommendations) {
        recList.innerHTML = data.recommendations.map((r) => `<li>${RAG.utils.escapeHtml(r)}</li>`).join('');
      }

      // Counts
      const dist = data.risk_distribution || {};
      document.getElementById('dist-low-count').textContent = dist.LOW ?? 0;
      document.getElementById('dist-med-count').textContent = dist.MEDIUM ?? 0;
      document.getElementById('dist-high-count').textContent = dist.HIGH ?? 0;
      document.getElementById('dist-crit-count').textContent = dist.CRITICAL ?? 0;

      const comp = data.compliance_distribution || {};
      document.getElementById('comp-compliant-count').textContent = comp.COMPLIANT ?? 0;
      document.getElementById('comp-review-count').textContent = comp.REVIEW_REQUIRED ?? 0;
      document.getElementById('comp-flagged-count').textContent = comp.FLAGGED ?? 0;
    },

    loadAuditLogs: async function () {
      const tableBody = document.getElementById('audit-logs-table-body');
      if (!tableBody) return;

      tableBody.innerHTML = `
        <tr>
          <td colspan="9" style="text-align: center; padding: 24px; color: var(--text-muted);">
            Fetching audit logs...
          </td>
        </tr>
      `;

      const search = document.getElementById('audit-filter-search')?.value.trim() || undefined;
      const category = document.getElementById('audit-filter-category')?.value || undefined;
      const risk = document.getElementById('audit-filter-risk')?.value || undefined;
      const compliance = document.getElementById('audit-filter-compliance')?.value || undefined;

      try {
        const res = await API.getAuditLogs({
          skip: this.currentPage * this.pageSize,
          limit: this.pageSize,
          domain_category: category,
          risk_level: risk,
          compliance_status: compliance,
          search: search,
        });

        this.totalRecords = res.total || 0;
        this.renderLogsTable(res.items || []);
        this.updatePagination();
      } catch (err) {
        tableBody.innerHTML = `
          <tr>
            <td colspan="9" style="text-align: center; padding: 24px; color: #ef4444;">
              Failed to load audit logs: ${RAG.utils.escapeHtml(err.message || 'Network error')}
            </td>
          </tr>
        `;
      }
    },

    renderLogsTable: function (items) {
      const tableBody = document.getElementById('audit-logs-table-body');
      if (!tableBody) return;

      if (!items || items.length === 0) {
        tableBody.innerHTML = `
          <tr>
            <td colspan="9" style="text-align: center; padding: 24px; color: var(--text-muted);">
              No audit records matching query parameters.
            </td>
          </tr>
        `;
        return;
      }

      tableBody.innerHTML = items
        .map((rec) => {
          const ts = rec.timestamp ? new Date(rec.timestamp).toLocaleString() : 'N/A';
          const riskClass = (rec.risk_level || 'low').toLowerCase();
          const compClass = (rec.compliance_status || 'compliant').toLowerCase().replace('_', '-');
          const remarkPreview = rec.compliance_remark ? RAG.utils.escapeHtml(rec.compliance_remark.substring(0, 40)) + (rec.compliance_remark.length > 40 ? '...' : '') : '<span style="color:var(--text-muted);">—</span>';

          return `
            <tr>
              <td style="font-family: monospace; font-size: 0.72rem; white-space: nowrap;">${ts}</td>
              <td><span style="font-size: 0.72rem; font-weight: 600; color: #38bdf8;">${RAG.utils.escapeHtml(rec.domain_category)}</span></td>
              <td><strong>${RAG.utils.escapeHtml(rec.event_name)}</strong></td>
              <td><span style="font-size: 0.72rem; font-weight: 600;">${RAG.utils.escapeHtml(rec.execution_status)}</span></td>
              <td><span class="risk-chip ${riskClass}">${RAG.utils.escapeHtml(rec.risk_level)} (${rec.risk_score})</span></td>
              <td><span style="font-size: 0.72rem; color: var(--text-muted);">${RAG.utils.escapeHtml(rec.actor_username || rec.actor_role || 'system')}</span></td>
              <td style="font-size: 0.72rem;">${rec.latency_ms ? Math.round(rec.latency_ms) + 'ms' : '—'}</td>
              <td>
                <span class="compliance-status-badge ${compClass}" style="margin-right: 4px;">${RAG.utils.escapeHtml(rec.compliance_status)}</span>
                <span style="font-size: 0.72rem;">${remarkPreview}</span>
              </td>
              <td>
                <button class="btn btn-outline edit-remark-btn" style="font-size: 0.68rem; padding: 3px 6px;" 
                  data-id="${rec.id}" data-status="${rec.compliance_status}" data-remark="${encodeURIComponent(rec.compliance_remark || '')}">
                  ✏️ Remark
                </button>
              </td>
            </tr>
          `;
        })
        .join('');

      // Attach click listeners to "Remark" buttons
      tableBody.querySelectorAll('.edit-remark-btn').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          const id = btn.getAttribute('data-id');
          const status = btn.getAttribute('data-status');
          const remark = decodeURIComponent(btn.getAttribute('data-remark') || '');

          this.openRemarkTab(id, status, remark);
        });
      });
    },

    updatePagination: function () {
      const info = document.getElementById('audit-pagination-info');
      const prevBtn = document.getElementById('audit-prev-page-btn');
      const nextBtn = document.getElementById('audit-next-page-btn');

      const start = this.totalRecords === 0 ? 0 : this.currentPage * this.pageSize + 1;
      const end = Math.min((this.currentPage + 1) * this.pageSize, this.totalRecords);

      if (info) info.textContent = `Showing ${start} - ${end} of ${this.totalRecords} records`;
      if (prevBtn) prevBtn.disabled = this.currentPage === 0;
      if (nextBtn) nextBtn.disabled = end >= this.totalRecords;
    },

    openRemarkTab: function (recordId, currentStatus, currentRemark) {
      // Switch to Tab 3
      const tabBtn = document.getElementById('audit-tab-btn-compliance');
      if (tabBtn) tabBtn.click();

      const idInput = document.getElementById('remark-record-id');
      const statusSelect = document.getElementById('remark-compliance-status');
      const textInput = document.getElementById('remark-text-input');

      if (idInput) idInput.value = recordId;
      if (statusSelect && currentStatus) statusSelect.value = currentStatus;
      if (textInput) textInput.value = currentRemark || '';
    },

    saveComplianceRemark: async function () {
      const recordId = document.getElementById('remark-record-id')?.value.trim();
      const status = document.getElementById('remark-compliance-status')?.value;
      const remark = document.getElementById('remark-text-input')?.value.trim();

      if (!recordId) {
        RAG.utils.showToast('Please specify a valid Audit Record ID', 'warning');
        return;
      }
      if (!remark) {
        RAG.utils.showToast('Please enter a compliance remark or auditor memo', 'warning');
        return;
      }

      try {
        await API.updateAuditComplianceRemark(recordId, remark, status);
        RAG.utils.showToast('Compliance remark and status updated successfully!', 'success');
        this.loadAuditLogs();
        this.loadRiskMetrics();
      } catch (err) {
        RAG.utils.showToast(`Failed updating remark: ${err.message || 'Error'}`, 'error');
      }
    },

    loadBackups: async function () {
      const container = document.getElementById('backups-cards-list');
      if (!container) return;

      container.innerHTML = `
        <div style="text-align: center; padding: 20px; color: var(--text-muted);">
          Loading backup archives...
        </div>
      `;

      try {
        const res = await API.listAuditBackups();
        const backups = res.backups || [];

        if (backups.length === 0) {
          container.innerHTML = `
            <div style="text-align: center; padding: 24px; color: var(--text-muted); font-size: 0.82rem;">
              No audit archives created yet. Click <strong>+ Create Legal Backup Now</strong> above.
            </div>
          `;
          return;
        }

        container.innerHTML = backups
          .map((b) => {
            const sizeKb = Math.round((b.size_bytes || 0) / 1024);
            const dateStr = b.created_at ? new Date(b.created_at).toLocaleString() : 'N/A';
            const verifiedBadge = b.integrity_verified
              ? `<span style="color: #10b981; font-weight: 600;">✓ Checksum Valid</span>`
              : `<span style="color: #ef4444; font-weight: 600;">⚠️ Verification Mismatch</span>`;

            return `
              <div class="backup-card">
                <div class="backup-info">
                  <div class="backup-filename">📦 ${RAG.utils.escapeHtml(b.filename)}</div>
                  <div class="backup-meta">
                    <span>Created: ${dateStr}</span>
                    <span>Size: ${sizeKb} KB</span>
                    <span>Operator: ${RAG.utils.escapeHtml(b.operator || 'system')}</span>
                    ${verifiedBadge}
                  </div>
                  <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 4px;">
                    SHA-256: <span class="backup-sha">${RAG.utils.escapeHtml(b.sha256 || 'None')}</span>
                  </div>
                </div>
              </div>
            `;
          })
          .join('');
      } catch (err) {
        container.innerHTML = `
          <div style="text-align: center; padding: 20px; color: #ef4444;">
            Failed to load backups: ${RAG.utils.escapeHtml(err.message || 'Error')}
          </div>
        `;
      }
    },

    triggerBackup: async function () {
      const memo = prompt('Enter a compliance remark / reason for generating this legal backup archive:', 'Mandatory compliance backup for audit review');
      if (memo === null) return;

      try {
        const res = await API.triggerAuditBackup(90, memo);
        RAG.utils.showToast(`Legal backup archive created! SHA-256: ${res.backup.sha256.substring(0, 16)}...`, 'success');
        this.loadBackups();
      } catch (err) {
        RAG.utils.showToast(`Failed creating backup: ${err.message || 'Error'}`, 'error');
      }
    },

    verifyIntegrity: async function () {
      const resultBox = document.getElementById('integrity-result-box');
      if (!resultBox) return;

      resultBox.style.display = 'block';
      resultBox.style.background = 'rgba(56, 189, 248, 0.1)';
      resultBox.style.color = '#38bdf8';
      resultBox.textContent = 'Cryptographically checking SHA-256 hash chaining across records...';

      try {
        const res = await API.verifyAuditIntegrity(500);
        if (res.verified) {
          resultBox.style.background = 'rgba(16, 185, 129, 0.15)';
          resultBox.style.color = '#10b981';
          resultBox.style.border = '1px solid rgba(16, 185, 129, 0.3)';
          resultBox.innerHTML = `
            <strong>✓ Cryptographic Chain Verified</strong>: All ${res.records_evaluated} audit records conform strictly to sequential SHA-256 tamper-evident hash chaining. Legal defensibility confirmed.
          `;
        } else {
          resultBox.style.background = 'rgba(239, 68, 68, 0.15)';
          resultBox.style.color = '#ef4444';
          resultBox.style.border = '1px solid rgba(239, 68, 68, 0.3)';
          resultBox.innerHTML = `
            <strong>⚠️ Cryptographic Tampering Detected</strong>: Found ${res.tampered_records_count} record(s) where previous hash chaining was broken.
          `;
        }
      } catch (err) {
        resultBox.style.background = 'rgba(239, 68, 68, 0.15)';
        resultBox.style.color = '#ef4444';
        resultBox.textContent = `Integrity check failed: ${err.message || 'Error'}`;
      }
    },
  };

  global.RAG = global.RAG || {};
  global.RAG.AuditRisk = AuditRisk;

  document.addEventListener('DOMContentLoaded', () => {
    AuditRisk.init();
  });
})(window);
