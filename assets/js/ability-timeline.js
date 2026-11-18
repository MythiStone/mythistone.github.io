// --- Boss timeline: a tap shows a cast's tooltip, another tap or scrolling the chart hides it ---
(function () {
    var open = null;
    function hide() {
        if (open) bootstrap.Tooltip.getOrCreateInstance(open).hide();
        open = null;
    }
    document.addEventListener('click', function (e) {
        var cast = e.target.closest('.tl-cast, .tl-band, .tl-segment, .tl-spread[data-bs-toggle]');
        if (cast !== open) hide();
        if (!cast) return;
        cast.focus();
        bootstrap.Tooltip.getOrCreateInstance(cast).show();
        open = cast;
    });
    document.addEventListener('scroll', function (e) {
        if (e.target.classList && e.target.classList.contains('tl-scroll')) hide();
    }, true);
})();
