/**
 * AIWN 2.0 — Ambient Loader
 *
 * Rotates atmospheric in-world quotes during loading states.
 * Cycles every 3 seconds with a fade transition.
 */

(function() {
  'use strict';

  var quotes = [
    'The ink dries slowly on the page of fate...',
    'In the space between words, worlds are born.',
    'Every power has a cost. Every cost has a lesson.',
    'The universe does not hurry, yet everything is accomplished.',
    'To name a thing is to begin to control it.',
    'The strongest walls are those built from broken promises.',
    'Even mountains began as whispers beneath the earth.',
    'The map is not the territory, but it dreams of becoming one.',
    'In the silence between heartbeats, empires rise and fall.',
    'The first step on any path is always taken in darkness.',
    'Power flows like water: always downhill, unless contained.',
    'A story untold is a life unlived.',
    'The stars remember what the earth forgets.',
    'Every ending is a doorway wearing a disguise.',
    'The void between chapters is where readers become dreamers.',
    'All great journeys begin with a single act of defiance.',
    'The quill knows what the hand has forgotten.',
    'Patience is the sharpest weapon in any arsenal.',
    'Between one breath and the next, a hero is made.',
    'The old texts say: to read is to remember someone else\'s truth.',
  ];

  var currentIndex = 0;
  var quoteElement = null;
  var intervalId = null;

  function init() {
    quoteElement = document.getElementById('ambient-quote');
    if (!quoteElement) return;

    // Show first quote
    quoteElement.textContent = quotes[0];
    quoteElement.style.opacity = '1';

    // Start cycling
    intervalId = setInterval(cycleQuote, 4000);
  }

  function cycleQuote() {
    if (!quoteElement) return;

    // Fade out
    quoteElement.style.transition = 'opacity 0.8s ease';
    quoteElement.style.opacity = '0';

    setTimeout(function() {
      // Advance to next quote
      currentIndex = (currentIndex + 1) % quotes.length;
      quoteElement.textContent = quotes[currentIndex];

      // Fade in
      quoteElement.style.opacity = '1';
    }, 800);
  }

  /**
   * Stop the ambient loader cycle.
   * Call this when loading is complete.
   */
  window.AIWN = window.AIWN || {};
  window.AIWN.stopAmbientLoader = function() {
    if (intervalId) {
      clearInterval(intervalId);
      intervalId = null;
    }
  };

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
