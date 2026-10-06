// Classic blocking script in <head>: sets html.js before first paint, so hidden "before" states
// (tickets sliding in, courts populating) only apply when they will actually be animated.
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!reduce && 'IntersectionObserver' in window) document.documentElement.classList.add('js');
})();
