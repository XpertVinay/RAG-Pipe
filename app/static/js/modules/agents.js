/**
 * Multi-Agent Collaborative System Client Module
 * Manages 6-agent workflows, real-time SSE progress, context compaction, and MCP execution.
 */

class MultiAgentModule {
  constructor() {
    this.modal = document.getElementById('agent-modal');
    this.closeBtn = document.getElementById('agent-modal-close');
    this.launchBtn = document.getElementById('agent-launch-btn');
    this.newRunBtn = document.getElementById('agent-new-run-btn');
    this.goalInput = document.getElementById('agent-goal-input');
    this.anonToggle = document.getElementById('agent-anonymous-toggle');
    this.maxTasksSelect = document.getElementById('agent-max-tasks');
    this.inputSection = document.getElementById('agent-input-section');
    this.dashboardSection = document.getElementById('agent-live-dashboard');
    this.progressBar = document.getElementById('agent-live-progress-bar');
    this.progressPct = document.getElementById('agent-live-progress-pct');
    this.statusText = document.getElementById('agent-live-status-text');
    this.subtasksContainer = document.getElementById('agent-subtasks-container');
    this.logsConsole = document.getElementById('agent-logs-console');
    this.tokensSavedElem = document.getElementById('telemetry-tokens-saved');
    this.ratioElem = document.getElementById('telemetry-ratio');
    this.finalReportWrapper = document.getElementById('agent-final-report-wrapper');
    this.finalReportContent = document.getElementById('agent-final-report-content');
    this.copyReportBtn = document.getElementById('copy-report-btn');
    this.sidebarWorkflowsList = document.getElementById('agents-workflow-list');
    this.clearWorkflowsBtn = document.getElementById('sidebar-clear-workflows-btn');
    this.clearLogsBtn = document.getElementById('sidebar-clear-logs-btn');
    this.deleteWfBtn = document.getElementById('agent-delete-wf-btn');
    this.currentWorkflowId = null;

    this.abortController = null;
    this.timerInterval = null;
    this.startTime = null;

    this.init();
  }

  init() {
    // Open modal buttons
    const navBtn = document.getElementById('open-agents-btn');
    if (navBtn) {
      navBtn.addEventListener('click', () => {
        this.resetForm();
        this.showModal();
      });
    }

    const sidebarBtn = document.getElementById('sidebar-launch-agent-btn');
    if (sidebarBtn) {
      sidebarBtn.addEventListener('click', () => {
        this.resetForm();
        this.showModal();
      });
    }

    if (this.closeBtn) {
      this.closeBtn.addEventListener('click', () => this.hideModal());
    }

    if (this.modal) {
      this.modal.addEventListener('click', (e) => {
        if (e.target === this.modal) this.hideModal();
      });
    }

    if (this.launchBtn) {
      this.launchBtn.addEventListener('click', () => this.launchWorkflow());
    }

    if (this.newRunBtn) {
      this.newRunBtn.addEventListener('click', () => this.resetForm());
    }

    // Admin & Super Admin maintenance handlers
    if (this.clearWorkflowsBtn) {
      this.clearWorkflowsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.confirmClearAllWorkflows();
      });
    }

    if (this.clearLogsBtn) {
      this.clearLogsBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.confirmClearLogs();
      });
    }

    if (this.deleteWfBtn) {
      this.deleteWfBtn.addEventListener('click', () => {
        if (this.currentWorkflowId) {
          this.deleteSingleWorkflow(this.currentWorkflowId);
        }
      });
    }

    const reqToggle = document.getElementById('toggle-requirements-btn');
    if (reqToggle) {
      reqToggle.addEventListener('click', () => {
        const content = document.getElementById('agent-requirements-content');
        const icon = document.getElementById('requirements-expand-icon');
        if (content) {
          const isHidden = content.style.display === 'none';
          content.style.display = isHidden ? 'block' : 'none';
          if (icon) icon.textContent = isHidden ? '▴ Hide Directives' : '▾ View Directives';
        }
      });
    }

    if (this.copyReportBtn) {
      this.copyReportBtn.addEventListener('click', () => {
        const text = this.finalReportContent?.innerText || '';
        if (text) {
          navigator.clipboard.writeText(text);
          if (window.showToast) window.showToast('Executive report copied to clipboard!', 'success');
        }
      });
    }

    // Preset buttons
    document.querySelectorAll('.agent-preset-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const goal = btn.getAttribute('data-goal');
        if (goal && this.goalInput) {
          this.goalInput.value = goal;
        }
      });
    });

    // Update admin buttons visibility on load and auth state changes
    window.addEventListener('auth:login', () => this.updateAdminVisibility());
    window.addEventListener('auth:logout', () => this.updateAdminVisibility());
    this.updateAdminVisibility();

    // Load existing workflows for sidebar
    this.loadWorkflowsList();
  }

  updateAdminVisibility() {
    const user = window.API?.getCurrentUser ? window.API.getCurrentUser() : null;
    const isAdmin = Boolean(user && (user.role === 'admin' || user.role === 'super_admin'));
    if (this.clearWorkflowsBtn) {
      this.clearWorkflowsBtn.style.display = isAdmin ? 'inline-flex' : 'none';
    }
    if (this.clearLogsBtn) {
      this.clearLogsBtn.style.display = isAdmin ? 'inline-flex' : 'none';
    }
  }

  async confirmClearAllWorkflows() {
    const confirmAction = async () => {
      const token = window.API?.getAccessToken ? window.API.getAccessToken() : null;
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      try {
        const res = await fetch('/api/v1/agents/workflows?clear_logs=true&optimize_db=true', {
          method: 'DELETE',
          headers,
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Failed to clear workflows');
        }
        if (window.showToast) {
          window.showToast(data.message || 'Workflows and logs cleared. Database storage optimized.', 'success');
        }
        this.hideModal();
        this.loadWorkflowsList();
      } catch (err) {
        console.error('Error clearing workflows:', err);
        if (window.showToast) window.showToast(err.message, 'error');
      }
    };

    if (window.RAG?.utils?.confirmModal) {
      window.RAG.utils.confirmModal({
        title: 'Clear Agent Workflows & Logs',
        headerIcon: '⚠️',
        itemIcon: '🤖',
        itemName: 'All Agent Workflows & Operational Logs',
        itemMeta: 'Super Admin / Admin Maintenance Action',
        prompt: 'Permanently delete all agent workflows, micro-task execution traces, and audit logs to optimize database storage? This action cannot be undone.',
        confirmText: 'Wipe & Optimize DB',
        confirmClass: 'btn btn-danger',
        onConfirm: confirmAction,
      });
    } else {
      if (confirm('Permanently delete all agent workflows, execution logs, and optimize database storage?')) {
        await confirmAction();
      }
    }
  }

  async confirmClearLogs() {
    const confirmAction = async () => {
      const token = window.API?.getAccessToken ? window.API.getAccessToken() : null;
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      try {
        const res = await fetch('/api/v1/agents/logs?optimize_db=true', {
          method: 'DELETE',
          headers,
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Failed to clear logs');
        }
        if (window.showToast) {
          window.showToast(data.message || 'Audit logs and execution traces cleared. Database optimized.', 'success');
        }
        this.loadWorkflowsList();
      } catch (err) {
        console.error('Error clearing logs:', err);
        if (window.showToast) window.showToast(err.message, 'error');
      }
    };

    if (window.RAG?.utils?.confirmModal) {
      window.RAG.utils.confirmModal({
        title: 'Purge Operational & Audit Logs',
        headerIcon: '🧹',
        itemIcon: '📜',
        itemName: 'Audit Trails & Execution Logs',
        itemMeta: 'Database Optimization & Log Cleanup',
        prompt: 'Purge all system audit logs and task execution traces to reclaim disk space?',
        confirmText: 'Purge Logs',
        confirmClass: 'btn btn-danger',
        onConfirm: confirmAction,
      });
    } else {
      if (confirm('Purge all system audit logs and agent execution traces to optimize database storage?')) {
        await confirmAction();
      }
    }
  }

  async deleteSingleWorkflow(wfId) {
    const confirmAction = async () => {
      const token = window.API?.getAccessToken ? window.API.getAccessToken() : null;
      const headers = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      try {
        const res = await fetch(`/api/v1/agents/workflows/${wfId}`, {
          method: 'DELETE',
          headers,
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Failed to delete workflow');
        }
        if (window.showToast) {
          window.showToast(data.message || 'Workflow deleted.', 'success');
        }
        this.hideModal();
        this.loadWorkflowsList();
      } catch (err) {
        console.error('Error deleting workflow:', err);
        if (window.showToast) window.showToast(err.message, 'error');
      }
    };

    if (window.RAG?.utils?.confirmModal) {
      window.RAG.utils.confirmModal({
        title: 'Delete Agent Workflow',
        headerIcon: '🗑️',
        itemIcon: '🤖',
        itemName: `Workflow ${wfId}`,
        itemMeta: 'Permanent Deletion',
        prompt: 'Are you sure you want to delete this specific workflow and its subtasks?',
        confirmText: 'Delete',
        confirmClass: 'btn btn-danger',
        onConfirm: confirmAction,
      });
    } else {
      if (confirm('Delete this workflow and its subtasks?')) {
        await confirmAction();
      }
    }
  }

  showModal() {
    if (this.modal) {
      this.modal.classList.add('active');
      this.modal.style.display = 'flex';
      this.modal.setAttribute('aria-hidden', 'false');
    }
  }

  hideModal() {
    if (this.modal) {
      this.modal.classList.remove('active');
      this.modal.style.display = 'none';
      this.modal.setAttribute('aria-hidden', 'true');
    }
  }

  resetForm() {
    if (this.inputSection) this.inputSection.style.display = 'block';
    if (this.dashboardSection) this.dashboardSection.style.display = 'none';
    if (this.finalReportWrapper) this.finalReportWrapper.style.display = 'none';
    const reqWrapper = document.getElementById('agent-requirements-wrapper');
    if (reqWrapper) reqWrapper.style.display = 'none';
    const depWrapper = document.getElementById('agent-deployment-wrapper');
    if (depWrapper) depWrapper.style.display = 'none';
    if (this.progressBar) this.progressBar.style.width = '0%';
    if (this.progressPct) this.progressPct.textContent = '0%';
    if (this.subtasksContainer) this.subtasksContainer.innerHTML = '';
    if (this.logsConsole) this.logsConsole.innerHTML = '<div>[System] Ready for multi-agent workflow.</div>';
    this.resetStages();
    this.stopTimer();
  }

  resetStages() {
    for (let i = 0; i <= 5; i++) {
      const card = document.getElementById(`agent-stage-${i}`);
      if (card) {
        card.style.borderColor = 'var(--border-color)';
        card.style.background = 'rgba(255,255,255,0.03)';
      }
    }
  }

  setStageActive(index) {
    this.resetStages();
    for (let i = 0; i <= index; i++) {
      const card = document.getElementById(`agent-stage-${i}`);
      if (card) {
        if (i === index) {
          card.style.borderColor = '#818cf8';
          card.style.background = 'rgba(99, 102, 241, 0.15)';
        } else {
          card.style.borderColor = '#10b981';
          card.style.background = 'rgba(16, 185, 129, 0.08)';
        }
      }
    }
  }

  appendLog(msg) {
    if (!this.logsConsole) return;
    const line = document.createElement('div');
    const time = new Date().toLocaleTimeString();
    line.textContent = `[${time}] ${msg}`;
    this.logsConsole.appendChild(line);
    this.logsConsole.scrollTop = this.logsConsole.scrollHeight;
  }

  startTimer() {
    this.startTime = Date.now();
    const timerElem = document.getElementById('agent-elapsed-timer');
    if (this.timerInterval) clearInterval(this.timerInterval);
    this.timerInterval = setInterval(() => {
      const elapsed = Math.round((Date.now() - this.startTime) / 1000);
      if (timerElem) timerElem.textContent = `Elapsed: ${elapsed}s`;
    }, 1000);
  }

  stopTimer() {
    if (this.timerInterval) {
      clearInterval(this.timerInterval);
      this.timerInterval = null;
    }
  }

  async launchWorkflow() {
    const goal = this.goalInput?.value?.trim();
    if (!goal) {
      if (window.showToast) window.showToast('Please enter an objective or goal.', 'warning');
      return;
    }

    const anonymous = this.anonToggle ? this.anonToggle.checked : true;
    const maxSubtasks = parseInt(this.maxTasksSelect?.value || '4', 10);

    // Switch view to dashboard
    if (this.inputSection) this.inputSection.style.display = 'none';
    if (this.dashboardSection) this.dashboardSection.style.display = 'block';

    this.appendLog(`Initiating multi-agent collaborative execution for: "${goal.slice(0, 70)}..."`);
    this.startTimer();

    if (this.abortController) this.abortController.abort();
    this.abortController = new AbortController();

    const headers = {
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
    };
    const token = window.API?.getAccessToken ? window.API.getAccessToken() : null;
    if (token) headers['Authorization'] = `Bearer ${token}`;

    try {
      const response = await fetch('/api/v1/agents/workflows/stream', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          goal,
          anonymous,
          max_subtasks: maxSubtasks,
        }),
        signal: this.abortController.signal,
      });

      if (!response.ok) {
        throw new Error(`Server returned HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop();

        for (const rawEvent of events) {
          if (!rawEvent.trim()) continue;
          let eventType = 'message';
          let eventData = '';

          for (const line of rawEvent.split('\n')) {
            if (line.startsWith('event:')) eventType = line.slice(6).trim();
            else if (line.startsWith('data:')) eventData = line.slice(5).trim();
          }

          if (eventData) {
            try {
              const parsed = JSON.parse(eventData);
              this.handleServerEvent(eventType, parsed);
            } catch (err) {
              console.error('Failed to parse Agent SSE JSON payload:', eventData, err);
            }
          }
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        this.appendLog(`[ERROR] ${err.message || 'Stream connection error'}`);
        if (this.statusText) this.statusText.textContent = 'Execution encountered an error.';
      }
    } finally {
      this.stopTimer();
      this.loadWorkflowsList();
    }
  }

  handleServerEvent(eventType, data) {
    if (data.progress !== undefined) {
      const pct = `${data.progress}%`;
      if (this.progressBar) this.progressBar.style.width = pct;
      if (this.progressPct) this.progressPct.textContent = pct;
    }

    if (data.message && this.statusText) {
      this.statusText.textContent = data.message;
    }

    this.appendLog(`[${data.agent_role || 'Agent'}] ${data.message || eventType}`);

    // Update active stage ribbon
    if (data.phase) {
      if (data.phase.includes('0. Decision')) this.setStageActive(0);
      else if (data.phase.includes('1. Research')) this.setStageActive(1);
      else if (data.phase.includes('2. Task Generator')) this.setStageActive(2);
      else if (data.phase.includes('3. Task Executor')) this.setStageActive(3);
      else if (data.phase.includes('4. Tasks Validator')) this.setStageActive(4);
      else if (data.phase.includes('5. Deployer')) this.setStageActive(5);
    }

    // Context window compaction telemetry
    if (eventType === 'context_compacted' && data.data?.metrics) {
      const m = data.data.metrics;
      if (this.tokensSavedElem) this.tokensSavedElem.textContent = `${m.tokens_saved.toLocaleString()} Saved`;
      if (this.ratioElem) this.ratioElem.textContent = `${m.compression_ratio}% reduction`;
    }

    // Generated subtasks
    if (eventType === 'tasks_generated' && data.data?.tasks) {
      this.renderSubtasks(data.data.tasks);
    }

    // Subtask validated
    if (eventType === 'task_validated' && data.data) {
      this.updateSubtaskValidation(data.data.task_number, data.data.validation);
    }

    // Workflow completed
    if (eventType === 'workflow_completed' && data.data) {
      this.setStageActive(5);
      if (this.finalReportWrapper) this.finalReportWrapper.style.display = 'block';
      if (this.finalReportContent) {
        this.finalReportContent.textContent = data.data.final_report || 'Workflow completed.';
      }
      if (window.showToast) {
        window.showToast('Multi-Agent Workflow execution complete!', 'success');
      }
    }
  }

  renderSubtasks(tasks, logicalErrors = []) {
    if (!this.subtasksContainer) return;
    this.subtasksContainer.innerHTML = '';

    const roleMap = {
      'decision_maker': '🧠 Decision Maker',
      'researcher': '🔍 Researcher',
      'task_generator': '📋 Task Generator',
      'task_executor': '⚡ Task Executor',
      'validator': '🛡️ Validator',
      'deployer': '🚀 Deployer',
    };

    tasks.forEach((t) => {
      const card = document.createElement('div');
      card.id = `subtask-card-${t.task_number}`;
      card.style.cssText = 'background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 8px; padding: 10px 12px; margin-bottom: 8px; transition: all 0.2s ease;';

      const toolsList = (t.assigned_tools && t.assigned_tools.length > 0) ? t.assigned_tools.join(', ') : 'native';
      const roleName = roleMap[t.agent_role] || '⚡ Task Executor';

      // Check validation result
      const val = t.validation_result || {};
      const isPassed = val.passed === true || (t.validation_score !== null && t.validation_score >= 0.7);
      const isPending = t.status === 'pending' && (!val || Object.keys(val).length === 0);

      let badgeBg = 'rgba(255,255,255,0.06)';
      let badgeColor = 'var(--text-muted)';
      let badgeLabel = 'Pending';

      if (!isPending) {
        if (isPassed) {
          badgeBg = 'rgba(16, 185, 129, 0.15)';
          badgeColor = '#10b981';
          badgeLabel = `PASSED (${t.validation_score ?? val.score ?? 1.0})`;
        } else {
          badgeBg = 'rgba(239, 68, 68, 0.15)';
          badgeColor = '#ef4444';
          badgeLabel = `FLAGGED (${t.validation_score ?? val.score ?? 0.3})`;
        }
      }

      // Format output data
      let outputDisplay = '';
      if (t.output_data && Object.keys(t.output_data).length > 0) {
        if (typeof t.output_data === 'string') {
          outputDisplay = t.output_data;
        } else if (t.output_data.summary) {
          outputDisplay = t.output_data.summary;
        } else {
          try {
            outputDisplay = JSON.stringify(t.output_data, null, 2);
          } catch (e) {
            outputDisplay = String(t.output_data);
          }
        }
      } else {
        outputDisplay = `Operation performed by ${roleName} using [${toolsList}] via [${t.mcp_provider || 'native'}] provider.`;
      }

      // Check matching logical errors for this task
      const taskErrors = logicalErrors.filter(err => err.task_number === t.task_number || err.task_title === t.title);

      // Validation feedback
      let feedbackText = val.feedback || (isPassed ? 'All operational acceptance criteria and verification gates satisfied.' : 'One or more execution criteria flagged for review.');
      if (taskErrors.length > 0) {
        feedbackText += ' • Alerts: ' + taskErrors.map(e => e.message || e.note || e.type).join(' | ');
      }

      card.innerHTML = `
        <div class="subtask-card-header" style="display: flex; justify-content: space-between; align-items: flex-start; cursor: pointer; gap: 8px;">
          <div style="flex: 1; min-width: 0;">
            <div style="display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 4px;">
              <span style="font-weight: 700; color: #818cf8; font-size: 0.8rem;">#${t.task_number}</span>
              <span style="font-weight: 600; color: var(--text-main); font-size: 0.82rem;">${this.escapeHtml(t.title)}</span>
              <span style="font-size: 0.65rem; background: rgba(99, 102, 241, 0.15); color: #818cf8; padding: 1px 6px; border-radius: 4px; font-weight: 600;">
                ${roleName}
              </span>
            </div>
            <div style="font-size: 0.68rem; color: var(--text-muted); display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <span>Tool: <strong style="color: #38bdf8;">${toolsList}</strong></span>
              <span>•</span>
              <span>Provider: <strong style="color: #34d399;">${t.mcp_provider || 'native'}</strong></span>
              <span>•</span>
              <span id="subtask-toggle-hint-${t.task_number}" style="color: var(--accent-primary); font-weight: 500;">
                ▾ Details &amp; Fulfillment
              </span>
            </div>
          </div>
          <div id="subtask-badge-${t.task_number}" style="font-size: 0.68rem; padding: 2px 8px; border-radius: 4px; background: ${badgeBg}; color: ${badgeColor}; font-weight: 700; white-space: nowrap;">
            ${badgeLabel}
          </div>
        </div>

        <!-- Collapsible Details Body -->
        <div id="subtask-details-${t.task_number}" style="display: none; margin-top: 10px; padding-top: 10px; border-top: 1px solid rgba(255, 255, 255, 0.08); font-size: 0.74rem;">
          <!-- 1. Requirements Scope -->
          <div style="margin-bottom: 8px;">
            <div style="font-weight: 700; color: #818cf8; font-size: 0.68rem; text-transform: uppercase; margin-bottom: 2px;">
              📌 Requirements &amp; Scope:
            </div>
            <div style="color: var(--text-muted); line-height: 1.4; background: rgba(255,255,255,0.02); padding: 6px 8px; border-radius: 4px;">
              ${this.escapeHtml(t.description || 'No specific requirement description recorded.')}
            </div>
          </div>

          <!-- 2. Agent Operation & Output -->
          <div style="margin-bottom: 8px;">
            <div style="font-weight: 700; color: #38bdf8; font-size: 0.68rem; text-transform: uppercase; margin-bottom: 2px;">
              ⚡ Agent Execution &amp; Output:
            </div>
            <div style="color: var(--text-main); line-height: 1.4; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.05); padding: 6px 8px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; white-space: pre-wrap; max-height: 140px; overflow-y: auto;">
              ${this.escapeHtml(outputDisplay)}
            </div>
          </div>

          <!-- 3. Validation & Acceptance Criteria Fulfillment -->
          <div>
            <div style="font-weight: 700; color: #10b981; font-size: 0.68rem; text-transform: uppercase; margin-bottom: 2px;">
              🛡️ Acceptance Criteria &amp; Verification Verdict:
            </div>
            <div style="background: ${isPassed ? 'rgba(16, 185, 129, 0.06)' : 'rgba(239, 68, 68, 0.06)'}; border: 1px solid ${isPassed ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)'}; border-radius: 4px; padding: 6px 8px;">
              <div style="display: flex; justify-content: space-between; margin-bottom: 3px; font-size: 0.7rem;">
                <span><strong>Status:</strong> <span style="color: ${isPassed ? '#10b981' : '#ef4444'}; font-weight: 700;">${isPassed ? 'PASSED' : 'FLAGGED'}</span></span>
                <span><strong>Verification Score:</strong> ${t.validation_score ?? val.score ?? (isPassed ? 1.0 : 0.3)}</span>
              </div>
              <div style="color: var(--text-muted); font-size: 0.7rem; line-height: 1.4;">
                ${this.escapeHtml(feedbackText)}
              </div>
            </div>
          </div>
        </div>
      `;

      // Click header to toggle details
      const header = card.querySelector('.subtask-card-header');
      if (header) {
        header.addEventListener('click', () => {
          const details = document.getElementById(`subtask-details-${t.task_number}`);
          const hint = document.getElementById(`subtask-toggle-hint-${t.task_number}`);
          if (details) {
            const isHidden = details.style.display === 'none';
            details.style.display = isHidden ? 'block' : 'none';
            if (hint) {
              hint.textContent = isHidden ? '▴ Collapse Details' : '▾ Details & Fulfillment';
            }
          }
        });
      }

      this.subtasksContainer.appendChild(card);
    });
  }

  escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  updateSubtaskValidation(taskNumber, validation) {
    const badge = document.getElementById(`subtask-badge-${taskNumber}`);
    const card = document.getElementById(`subtask-card-${taskNumber}`);
    if (badge) {
      if (validation.passed) {
        badge.textContent = `PASSED (${validation.score || 1.0})`;
        badge.style.background = 'rgba(16, 185, 129, 0.15)';
        badge.style.color = '#10b981';
        badge.style.fontWeight = '700';
      } else {
        badge.textContent = `FLAGGED (${validation.score || 0.3})`;
        badge.style.background = 'rgba(239, 68, 68, 0.15)';
        badge.style.color = '#ef4444';
      }
    }
    if (card && validation.passed) {
      card.style.borderColor = 'rgba(16, 185, 129, 0.3)';
    }
  }

  async loadWorkflowsList() {
    if (!this.sidebarWorkflowsList) return;
    this.updateAdminVisibility();

    try {
      const token = window.API?.getAccessToken ? window.API.getAccessToken() : null;
      const headers = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch('/api/v1/agents/workflows?limit=25', { headers });
      if (!res.ok) return;
      const workflows = await res.json();

      const user = window.API?.getCurrentUser ? window.API.getCurrentUser() : null;
      const isAdmin = Boolean(user && (user.role === 'admin' || user.role === 'super_admin'));

      if (!workflows || workflows.length === 0) {
        this.sidebarWorkflowsList.innerHTML = `
          <div style="text-align: center; padding: 20px 10px; color: var(--text-muted); font-size: 0.8rem;">
            No past workflows recorded.
          </div>
        `;
        return;
      }

      this.sidebarWorkflowsList.innerHTML = '';
      workflows.forEach((wf) => {
        const canDelete = isAdmin || (user && wf.user_id === user.id);
        const item = document.createElement('div');
        item.style.cssText = 'padding: 8px 10px; margin-bottom: 6px; background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 6px; cursor: pointer; transition: all 0.2s ease; position: relative;';
        item.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
            <span style="font-weight: 600; font-size: 0.78rem; color: var(--text-main); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 160px;">
              ${this.escapeHtml(wf.title)}
            </span>
            <div style="display: flex; align-items: center; gap: 4px;">
              <span style="font-size: 0.62rem; padding: 1px 5px; border-radius: 4px; background: ${wf.status === 'completed' ? 'rgba(16,185,129,0.15)' : 'rgba(99,102,241,0.15)'}; color: ${wf.status === 'completed' ? '#10b981' : '#818cf8'}; text-transform: uppercase;">
                ${wf.status}
              </span>
              ${canDelete ? `
                <button class="delete-wf-item-btn" title="Delete workflow" data-wf-id="${wf.id}" style="background: none; border: none; cursor: pointer; color: #ef4444; padding: 1px 4px; font-size: 0.72rem; border-radius: 3px; line-height: 1; opacity: 0.75; transition: opacity 0.2s ease;">
                  ✕
                </button>
              ` : ''}
            </div>
          </div>
          <div style="font-size: 0.65rem; color: var(--text-muted);">
            ${wf.task_count} subtasks • ${new Date(wf.created_at).toLocaleDateString()}
          </div>
        `;

        item.addEventListener('click', (e) => {
          if (e.target.closest('.delete-wf-item-btn')) return;
          this.showModal();
          this.loadWorkflowDetail(wf.id);
        });

        const deleteBtn = item.querySelector('.delete-wf-item-btn');
        if (deleteBtn) {
          deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const id = deleteBtn.getAttribute('data-wf-id');
            if (id) this.deleteSingleWorkflow(id);
          });
        }

        this.sidebarWorkflowsList.appendChild(item);
      });
    } catch (e) {
      console.warn('Failed to load workflows list:', e);
    }
  }

  async loadWorkflowDetail(wfId) {
    try {
      this.currentWorkflowId = wfId;
      const token = window.API?.getAccessToken ? window.API.getAccessToken() : null;
      const headers = {};
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`/api/v1/agents/workflows/${wfId}`, { headers });
      if (!res.ok) return;
      const wf = await res.json();

      const user = window.API?.getCurrentUser ? window.API.getCurrentUser() : null;
      const canDelete = Boolean(user && (user.role === 'admin' || user.role === 'super_admin' || wf.user_id === user.id));
      if (this.deleteWfBtn) {
        this.deleteWfBtn.style.display = canDelete ? 'inline-flex' : 'none';
      }

      if (this.inputSection) this.inputSection.style.display = 'none';
      if (this.dashboardSection) this.dashboardSection.style.display = 'block';

      if (this.statusText) {
        this.statusText.textContent = `Workflow: ${wf.title}`;
      }
      if (this.progressBar) this.progressBar.style.width = '100%';
      if (this.progressPct) this.progressPct.textContent = '100%';
      this.setStageActive(5);

      // Context Compaction Telemetry
      if (wf.metrics?.context_compaction) {
        const cc = wf.metrics.context_compaction;
        if (this.tokensSavedElem) {
          this.tokensSavedElem.textContent = `${(cc.tokens_saved || 0).toLocaleString()} Saved`;
        }
        if (this.ratioElem) {
          this.ratioElem.textContent = `${cc.compression_ratio || 0}% reduction`;
        }
      }

      // Requirements Specification & Architecture Directives
      const reqWrapper = document.getElementById('agent-requirements-wrapper');
      const reqContent = document.getElementById('agent-requirements-content');
      const reqIcon = document.getElementById('requirements-expand-icon');
      if (reqWrapper && reqContent) {
        const spec = wf.requirements_spec || wf.metrics?.customer_advice || '';
        if (spec) {
          reqWrapper.style.display = 'block';
          reqContent.textContent = spec;
          reqContent.style.display = 'none';
          if (reqIcon) reqIcon.textContent = '▾ View Directives';
        } else {
          reqWrapper.style.display = 'none';
        }
      }

      // Deployer Health & Quality Gate
      const depWrapper = document.getElementById('agent-deployment-wrapper');
      const depBadge = document.getElementById('agent-deploy-health-badge');
      const depSummary = document.getElementById('agent-deploy-summary-text');
      const depErrors = document.getElementById('agent-deploy-errors-list');
      const logicalErrors = (wf.deployment_info && wf.deployment_info.logical_errors) || [];
      const syntaxErrors = (wf.deployment_info && wf.deployment_info.syntax_errors) || [];

      if (depWrapper && wf.deployment_info) {
        depWrapper.style.display = 'block';
        const health = (wf.deployment_info.health || 'operational').toUpperCase();
        if (depBadge) {
          depBadge.textContent = health;
          depBadge.style.background = health === 'HEALTHY' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(234, 179, 8, 0.15)';
          depBadge.style.color = health === 'HEALTHY' ? '#10b981' : '#eab308';
        }
        if (depSummary) {
          depSummary.textContent = `${syntaxErrors.length} syntax • ${logicalErrors.length} logical errors`;
        }
        if (depErrors) {
          if (logicalErrors.length > 0 || syntaxErrors.length > 0) {
            depErrors.style.display = 'block';
            depErrors.innerHTML = logicalErrors.map(e => `<div>⚠️ Task ${e.task_number || ''}: ${this.escapeHtml(e.message || e.note || e.type)}</div>`).join('');
          } else {
            depErrors.style.display = 'none';
          }
        }
      } else if (depWrapper) {
        depWrapper.style.display = 'none';
      }

      // Activity logs console
      if (this.logsConsole) {
        this.logsConsole.innerHTML = '';
        if (wf.deployment_info?.logs && wf.deployment_info.logs.length > 0) {
          wf.deployment_info.logs.forEach(l => {
            const div = document.createElement('div');
            div.textContent = `[Deployer] ${l}`;
            this.logsConsole.appendChild(div);
          });
        } else {
          const div = document.createElement('div');
          div.textContent = `[System] Workflow completed with ${wf.tasks?.length || 0} subtasks in ${wf.metrics?.duration_seconds || '60'}s.`;
          this.logsConsole.appendChild(div);
        }
      }

      // Render Subtasks with fulfillment & validation
      if (wf.tasks) {
        this.renderSubtasks(wf.tasks, logicalErrors);
      }

      // Executive Summary Report
      if (this.finalReportWrapper) this.finalReportWrapper.style.display = 'block';
      if (this.finalReportContent) {
        this.finalReportContent.textContent = wf.executive_summary || 'No summary available.';
      }
    } catch (e) {
      console.error('Failed to load workflow detail:', e);
    }
  }
}

// Instantiate on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  window.MultiAgent = new MultiAgentModule();
});
