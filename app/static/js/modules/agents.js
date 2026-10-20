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

    this.abortController = null;
    this.timerInterval = null;
    this.startTime = null;

    this.init();
  }

  init() {
    // Open modal buttons
    const navBtn = document.getElementById('open-agents-btn');
    if (navBtn) {
      navBtn.addEventListener('click', () => this.showModal());
    }

    const sidebarBtn = document.getElementById('sidebar-launch-agent-btn');
    if (sidebarBtn) {
      sidebarBtn.addEventListener('click', () => this.showModal());
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

    // Load existing workflows for sidebar
    this.loadWorkflowsList();
  }

  showModal() {
    if (this.modal) {
      this.modal.style.display = 'flex';
      this.modal.setAttribute('aria-hidden', 'false');
    }
  }

  hideModal() {
    if (this.modal) {
      this.modal.style.display = 'none';
      this.modal.setAttribute('aria-hidden', 'true');
    }
  }

  resetForm() {
    if (this.inputSection) this.inputSection.style.display = 'block';
    if (this.dashboardSection) this.dashboardSection.style.display = 'none';
    if (this.finalReportWrapper) this.finalReportWrapper.style.display = 'none';
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

  renderSubtasks(tasks) {
    if (!this.subtasksContainer) return;
    this.subtasksContainer.innerHTML = '';

    tasks.forEach((t) => {
      const card = document.createElement('div');
      card.id = `subtask-card-${t.task_number}`;
      card.style.cssText = 'background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 6px; padding: 8px 10px; display: flex; justify-content: space-between; align-items: center; font-size: 0.78rem;';

      const toolsList = t.assigned_tools.join(', ') || 'native';
      card.innerHTML = `
        <div>
          <span style="font-weight: 700; color: #818cf8; margin-right: 6px;">#${t.task_number}</span>
          <span style="font-weight: 600; color: var(--text-main);">${t.title}</span>
          <div style="font-size: 0.68rem; color: var(--text-muted); margin-top: 2px;">
            Tool: <span style="color: #3b82f6;">${toolsList}</span> • Provider: <span style="color: #10b981;">${t.mcp_provider}</span>
          </div>
        </div>
        <div id="subtask-badge-${t.task_number}" style="font-size: 0.68rem; padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.06); color: var(--text-muted);">
          Pending
        </div>
      `;
      this.subtasksContainer.appendChild(card);
    });
  }

  updateSubtaskValidation(taskNumber, validation) {
    const badge = document.getElementById(`subtask-badge-${taskNumber}`);
    const card = document.getElementById(`subtask-card-${taskNumber}`);
    if (badge) {
      if (validation.passed) {
        badge.textContent = `Passed (${validation.score})`;
        badge.style.background = 'rgba(16, 185, 129, 0.15)';
        badge.style.color = '#10b981';
        badge.style.fontWeight = '700';
      } else {
        badge.textContent = `Flagged`;
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
    try {
      const res = await fetch('/api/v1/agents/workflows?limit=10');
      if (!res.ok) return;
      const workflows = await res.json();

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
        const item = document.createElement('div');
        item.style.cssText = 'padding: 8px 10px; margin-bottom: 6px; background: rgba(255,255,255,0.02); border: 1px solid var(--border-color); border-radius: 6px; cursor: pointer; transition: all 0.2s ease;';
        item.innerHTML = `
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
            <span style="font-weight: 600; font-size: 0.78rem; color: var(--text-main); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 170px;">
              ${wf.title}
            </span>
            <span style="font-size: 0.62rem; padding: 1px 5px; border-radius: 4px; background: ${wf.status === 'completed' ? 'rgba(16,185,129,0.15)' : 'rgba(99,102,241,0.15)'}; color: ${wf.status === 'completed' ? '#10b981' : '#818cf8'}; text-transform: uppercase;">
              ${wf.status}
            </span>
          </div>
          <div style="font-size: 0.65rem; color: var(--text-muted);">
            ${wf.task_count} subtasks • ${new Date(wf.created_at).toLocaleDateString()}
          </div>
        `;

        item.addEventListener('click', () => {
          this.showModal();
          this.loadWorkflowDetail(wf.id);
        });

        this.sidebarWorkflowsList.appendChild(item);
      });
    } catch (e) {
      console.warn('Failed to load workflows list:', e);
    }
  }

  async loadWorkflowDetail(wfId) {
    try {
      const res = await fetch(`/api/v1/agents/workflows/${wfId}`);
      if (!res.ok) return;
      const wf = await res.json();

      if (this.inputSection) this.inputSection.style.display = 'none';
      if (this.dashboardSection) this.dashboardSection.style.display = 'block';

      if (this.statusText) this.statusText.textContent = `Viewing Workflow: ${wf.title}`;
      if (this.progressBar) this.progressBar.style.width = '100%';
      if (this.progressPct) this.progressPct.textContent = '100%';
      this.setStageActive(5);

      if (wf.tasks) {
        this.renderSubtasks(wf.tasks);
        wf.tasks.forEach((t) => {
          this.updateSubtaskValidation(t.task_number, t.validation_result || { passed: true, score: 1.0 });
        });
      }

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
