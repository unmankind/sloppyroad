/**
 * SloppyRoad — Main Application JavaScript
 *
 * Handles:
 * - HTMX configuration (boost, indicator class)
 * - SSE chapter streaming consumer
 * - Notification bell polling
 * - Theme toggle
 * - Time-on-page tracking for reader signals
 */

(function() {
  'use strict';

  // ── HTMX Configuration ──────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function() {
    // Configure HTMX defaults if available
    if (typeof htmx !== 'undefined') {
      htmx.config.indicatorClass = 'htmx-indicator';
      htmx.config.defaultSwapStyle = 'innerHTML';
      htmx.config.historyCacheSize = 10;
      htmx.config.defaultSettleDelay = 100;
      htmx.config.withCredentials = true;

      // Enable boosting for all internal links after swap
      document.body.addEventListener('htmx:afterSwap', function(event) {
        // Re-initialize any components in the swapped content
        initializeComponents(event.detail.target);
      });

      // Add page-turn animation on navigation
      document.body.addEventListener('htmx:beforeSwap', function(event) {
        if (event.detail.target === document.querySelector('main')) {
          event.detail.target.classList.add('animate-fade-in');
        }
      });
    }

    // Initialize all components on page load
    initializeComponents(document);
  });


  // ── Component Initialization ─────────────────────────────────────────

  function initializeComponents(root) {
    // Close notification dropdown when clicking outside
    document.addEventListener('click', function(e) {
      var dropdown = document.getElementById('notification-dropdown');
      var bell = document.querySelector('.notification-bell');
      if (dropdown && bell && !bell.contains(e.target) && !dropdown.contains(e.target)) {
        dropdown.classList.add('hidden');
      }
    });

    // Star rating hover effect
    var starWidgets = root.querySelectorAll('.star-rating:not(.star-rating-display)');
    starWidgets.forEach(function(widget) {
      var stars = widget.querySelectorAll('.star');
      stars.forEach(function(star, index) {
        star.addEventListener('mouseenter', function() {
          stars.forEach(function(s, i) {
            if (i <= index) {
              s.classList.add('filled');
            } else {
              s.classList.remove('filled');
            }
          });
        });
      });
      widget.addEventListener('mouseleave', function() {
        stars.forEach(function(s) {
          if (!s.dataset.selected) {
            s.classList.remove('filled');
          }
        });
      });
    });

    // Mobile nav toggle
    var navToggle = root.querySelector('.navbar-toggle');
    if (navToggle) {
      navToggle.addEventListener('click', function() {
        var links = document.getElementById('nav-links');
        if (links) links.classList.toggle('open');
      });
    }
  }


  // ── SSE Chapter Streaming ────────────────────────────────────────────

  /**
   * Connect to an SSE endpoint for chapter streaming.
   * Used by the chapter_generating.html page.
   *
   * @param {string} url - The SSE endpoint URL
   * @param {object} handlers - Event handler callbacks
   *   - onToken(text): Called for each text token
   *   - onStatus(status, progress): Called for status updates
   *   - onComplete(data): Called when generation completes
   *   - onError(message): Called on error
   * @returns {EventSource} The EventSource connection
   */
  window.AIWN = window.AIWN || {};
  window.AIWN.connectStream = function(url, handlers) {
    var source = new EventSource(url);

    source.addEventListener('token', function(e) {
      var data = JSON.parse(e.data);
      if (handlers.onToken) handlers.onToken(data.text);
    });

    source.addEventListener('status', function(e) {
      var data = JSON.parse(e.data);
      if (handlers.onStatus) handlers.onStatus(data.status, data.progress);
    });

    source.addEventListener('complete', function(e) {
      var data = JSON.parse(e.data);
      source.close();
      if (handlers.onComplete) handlers.onComplete(data);
    });

    source.addEventListener('error', function(e) {
      if (e.data) {
        var data = JSON.parse(e.data);
        if (handlers.onError) handlers.onError(data.message || 'Generation failed');
      }
      source.close();
    });

    source.onerror = function() {
      if (source.readyState === EventSource.CLOSED) {
        if (handlers.onError) handlers.onError('Connection lost');
      }
    };

    return source;
  };


  // ── Notification Polling ─────────────────────────────────────────────
  // HTMX handles this via hx-trigger="every 30s" on the notification bell.
  // No additional JS needed — the bell component self-polls.


  // ── Time-on-Page Tracking ────────────────────────────────────────────
  // Handled in reader_base.html via inline script with sendBeacon.
  // Keeping it in the template since it needs template variables.


  // ── Utility Functions ────────────────────────────────────────────────

  /**
   * Format a number with commas (e.g., 12345 -> "12,345")
   */
  window.AIWN.formatNumber = function(n) {
    return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  };

  /**
   * Debounce a function call
   */
  window.AIWN.debounce = function(func, wait) {
    var timeout;
    return function() {
      var context = this;
      var args = arguments;
      clearTimeout(timeout);
      timeout = setTimeout(function() {
        func.apply(context, args);
      }, wait);
    };
  };

})();
