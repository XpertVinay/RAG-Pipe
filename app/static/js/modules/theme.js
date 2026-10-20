/**
 * RAG Agent - Theme Manager
 * Supports: Dark, Light, and Default (System style/theme)
 * Persists theme preference across sessions in localStorage with OS media-query syncing.
 */

(function () {
  'use strict';

  const STORAGE_KEY = 'rag_agent_theme';
  const VALID_MODES = ['system', 'dark', 'cyber', 'sunset', 'light'];

  const ICONS = {
    system: '💻',
    dark: '🌌',
    cyber: '⚡',
    sunset: '🌅',
    light: '☀️'
  };

  const LABELS = {
    system: 'System',
    dark: 'Midnight',
    cyber: 'Cyber Neon',
    sunset: 'Sunset Solar',
    light: 'Arctic Light'
  };

  /**
   * Get the saved theme mode preference ('system', 'dark', 'cyber', 'sunset', or 'light').
   * Defaults to 'system'.
   */
  function getSavedMode() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && VALID_MODES.includes(saved)) {
        return saved;
      }
    } catch (e) {
      console.warn('ThemeManager: Unable to read from localStorage', e);
    }
    return 'system';
  }

  /**
   * Determine the effective theme ('dark', 'cyber', 'sunset', or 'light') based on chosen mode.
   */
  function resolveEffectiveTheme(mode) {
    if (mode === 'dark' || mode === 'cyber' || mode === 'sunset' || mode === 'light') {
      return mode;
    }
    // 'system' mode: detect system OS preference
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
    return 'light';
  }

  /**
   * Apply theme to <html> / <body> and update all theme controls in the DOM.
   */
  function applyTheme(mode, persist = true) {
    if (!VALID_MODES.includes(mode)) {
      mode = 'system';
    }

    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, mode);
      } catch (e) {
        console.warn('ThemeManager: Unable to save to localStorage', e);
      }
    }

    const effective = resolveEffectiveTheme(mode);
    const root = document.documentElement;

    root.setAttribute('data-theme', effective);
    root.setAttribute('data-theme-mode', mode);

    // Also update body classes for compatibility
    if (document.body) {
      document.body.classList.remove('theme-light', 'theme-dark', 'theme-cyber', 'theme-sunset');
      document.body.classList.add(`theme-${effective}`);
      if (effective === 'light') {
        document.body.classList.add('theme-light');
      } else {
        document.body.classList.add('theme-dark');
      }
    }

    // Update all UI elements
    updateThemeUI(mode, effective);

    // Dispatch custom event for any listeners
    window.dispatchEvent(new CustomEvent('themechange', {
      detail: { mode, effectiveTheme: effective }
    }));
  }

  /**
   * Update theme switchers, dropdowns, and settings inputs.
   */
  function updateThemeUI(mode, effective) {
    // 1. Update dropdown triggers
    const containers = document.querySelectorAll('.theme-dropdown-container');
    containers.forEach(container => {
      const iconEl = container.querySelector('.theme-current-icon');
      const labelEl = container.querySelector('.theme-current-label');

      if (iconEl) {
        iconEl.textContent = ICONS[mode] || ICONS.system;
      }
      if (labelEl) {
        labelEl.textContent = LABELS[mode] || LABELS.system;
      }

      // Update active state in menu items
      const options = container.querySelectorAll('.theme-option');
      options.forEach(opt => {
        const optChoice = opt.getAttribute('data-theme-choice');
        const isActive = optChoice === mode;
        opt.classList.toggle('active', isActive);
        opt.setAttribute('aria-selected', isActive ? 'true' : 'false');
        const check = opt.querySelector('.theme-option-check, .option-indicator');
        if (check) {
          check.style.opacity = isActive ? '1' : '0';
        }
      });
    });

    // 2. Update standalone select if present (e.g. in Settings Modal)
    const selects = document.querySelectorAll('#theme-select, select[name="theme"]');
    selects.forEach(select => {
      if (select.value !== mode) {
        select.value = mode;
      }
    });

    // 3. Update profile menu theme label & chips
    const profileThemeName = document.getElementById('profile-current-theme-name');
    if (profileThemeName) {
      profileThemeName.textContent = LABELS[mode] || LABELS.system;
    }
    document.querySelectorAll('.profile-theme-btn').forEach(btn => {
      const choice = btn.getAttribute('data-theme-choice');
      const isActive = choice === mode;
      btn.classList.toggle('active', isActive);
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
  }

  /**
   * Close all dropdown menus.
   */
  function closeAllMenus() {
    document.querySelectorAll('.theme-menu.show').forEach(menu => {
      menu.classList.remove('show');
      const btn = menu.closest('.theme-dropdown-container')?.querySelector('.theme-toggle-btn');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });
    document.querySelectorAll('.profile-dropdown-menu.show').forEach(menu => {
      menu.classList.remove('show');
      const btn = document.getElementById('auth-user-btn');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });
    document.querySelectorAll('.room-dropdown-menu.show').forEach(menu => {
      menu.classList.remove('show');
      const btn = document.getElementById('room-dropdown-btn');
      if (btn) btn.setAttribute('aria-expanded', 'false');
    });
  }

  /**
   * Initialize theme listeners, event delegation, and OS listener.
   */
  function initTheme() {
    const currentMode = getSavedMode();
    applyTheme(currentMode, false);

    // Watch OS system preference changes
    if (window.matchMedia) {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      const handleMediaChange = () => {
        if (getSavedMode() === 'system') {
          applyTheme('system', false);
        }
      };

      if (mediaQuery.addEventListener) {
        mediaQuery.addEventListener('change', handleMediaChange);
      } else if (mediaQuery.addListener) {
        mediaQuery.addListener(handleMediaChange);
      }
    }

    // Watch cross-tab storage changes
    window.addEventListener('storage', (e) => {
      if (e.key === STORAGE_KEY && e.newValue) {
        applyTheme(e.newValue, false);
      }
    });

    // Event delegation for clicks
    document.addEventListener('click', (e) => {
      // Toggle dropdown open/close
      const toggleBtn = e.target.closest('.theme-toggle-btn');
      if (toggleBtn) {
        e.preventDefault();
        e.stopPropagation();
        const container = toggleBtn.closest('.theme-dropdown-container');
        const menu = container ? container.querySelector('.theme-menu') : null;
        if (menu) {
          const isOpen = menu.classList.contains('show');
          closeAllMenus();
          if (!isOpen) {
            menu.classList.add('show');
            toggleBtn.setAttribute('aria-expanded', 'true');
          }
        }
        return;
      }

      // Select theme option
      const option = e.target.closest('.theme-option');
      if (option) {
        e.preventDefault();
        e.stopPropagation();
        const choice = option.getAttribute('data-theme-choice');
        if (choice && VALID_MODES.includes(choice)) {
          applyTheme(choice, true);
        }
        closeAllMenus();
        return;
      }

      // Close on outside click
      if (!e.target.closest('.theme-dropdown-container')) {
        closeAllMenus();
      }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeAllMenus();
      }
    });

    // Handle settings modal theme select change
    document.addEventListener('change', (e) => {
      if (e.target && (e.target.id === 'theme-select' || e.target.name === 'theme')) {
        const choice = e.target.value;
        if (choice && VALID_MODES.includes(choice)) {
          applyTheme(choice, true);
        }
      }
    });
  }

  // Auto-init when DOM is ready or immediately if already loaded
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initTheme);
  } else {
    initTheme();
  }

  // Export globally for programmatic control
  window.ThemeManager = {
    getMode: getSavedMode,
    getEffectiveTheme: () => resolveEffectiveTheme(getSavedMode()),
    setTheme: (mode) => applyTheme(mode, true),
    closeAllMenus
  };
})();
