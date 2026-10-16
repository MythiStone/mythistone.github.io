// Search page: renders window.MythiSearch results (site-search.js) as a full list.
(function () {
  'use strict';

  const MAX_RESULTS = 100;
  const search = window.MythiSearch;
  const input = document.getElementById('page-search-input');
  const btn = document.getElementById('page-search-btn');
  const clearBtn = document.getElementById('page-search-clear');
  const list = document.getElementById('page-search-list');
  const empty = document.getElementById('page-search-empty');
  const countEl = document.getElementById('page-search-count');
  const hint = 'Type at least ' + search.MIN_QUERY_LENGTH + ' characters to search.';

  function readQueryParam() {
    return new URLSearchParams(window.location.search).get('q') || '';
  }
  function writeQueryParam(q) {
    const u = new URL(window.location.href);
    if (!q) u.searchParams.delete('q'); else u.searchParams.set('q', q);
    window.history.replaceState({}, '', u.toString());
  }

  function showEmpty(msg) {
    list.innerHTML = '';
    empty.classList.remove('d-none');
    empty.querySelector('.card-body').textContent = msg;
    countEl.textContent = '';
  }

  function renderResults(results, q) {
    list.innerHTML = '';
    if (!results.length) {
      showEmpty('No results found for "' + q + '".');
      return;
    }
    empty.classList.add('d-none');
    countEl.textContent = results.length + ' result' + (results.length === 1 ? '' : 's');
    results.slice(0, MAX_RESULTS).forEach((entry) => list.appendChild(search.renderRow(entry)));
    if (results.length > MAX_RESULTS) {
      const more = document.createElement('div');
      more.className = 'mt-3 text-muted small';
      more.textContent = 'Showing ' + MAX_RESULTS + ' of ' + results.length + ' results. Refine your query.';
      list.appendChild(more);
    }
  }

  function doSearch(q) {
    q = (q || '').trim();
    writeQueryParam(q);
    if (q.length < search.MIN_QUERY_LENGTH) {
      showEmpty(hint);
      return;
    }
    if (!search.isReady()) {
      showEmpty('Loading the search index...');
      search.ready().then(
        () => { if (input.value.trim() === q) doSearch(q); },
        () => showEmpty('Failed to load the search index.')
      );
      return;
    }
    renderResults(search.search(q), q);
  }

  btn.addEventListener('click', () => doSearch(input.value));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); doSearch(input.value); }
    if (e.key === 'Escape') { input.value = ''; doSearch(''); }
  });
  clearBtn.addEventListener('click', () => { input.value = ''; doSearch(''); });

  const q = readQueryParam();
  input.value = q;
  doSearch(q);
})();
