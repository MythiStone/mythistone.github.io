// Spec Tierlist view toggle: whole specs vs every (spec, hero tree) pair.
// Both views are server-rendered; this only swaps which one is visible.
(function () {
  const panes = Array.from(document.querySelectorAll('#spec-tierlist .tier-view'));
  const buttons = Array.from(document.querySelectorAll('#spec-tierlist [data-tier-view-btn]'));
  if (!panes.length || !buttons.length) return;

  let current = 'spec';

  function show(view) {
    if (!panes.some((p) => p.getAttribute('data-tier-view') === view)) return;
    current = view;
    panes.forEach((p) => p.classList.toggle('d-none', p.getAttribute('data-tier-view') !== view));
    buttons.forEach((b) => {
      const on = b.getAttribute('data-tier-view-btn') === view;
      b.classList.toggle('active', on);
      b.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
  }

  buttons.forEach((b) => {
    b.addEventListener('click', () => {
      show(b.getAttribute('data-tier-view-btn'));
      if (window.MythiLink) MythiLink.sync();
    });
  });

  if (window.MythiLink) {
    MythiLink.registerState('view', {
      read: () => (current === 'spec' ? null : current),
      apply: (view) => show(view),
    });
  }
})();
