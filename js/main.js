(function () {
  var buttons = document.querySelectorAll('[data-filter]');
  var cards = document.querySelectorAll('#books-grid .card');
  var search = document.getElementById('book-search');
  var grid = document.getElementById('books-grid');
  var searchResults = document.getElementById('search-results');

  function activeFilter() {
    var active = document.querySelector('[data-filter].is-active');
    return active ? active.getAttribute('data-filter') : 'read';
  }

  function applyFilter(filterValue) {
    cards.forEach(function (card) {
      card.hidden = card.getAttribute('data-shelf') !== filterValue;
    });
  }

  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      buttons.forEach(function (b) { b.classList.remove('is-active'); });
      button.classList.add('is-active');
      if (!search || !search.value.trim()) {
        if (searchResults) { searchResults.hidden = true; }
        if (grid) { grid.hidden = false; }
        applyFilter(button.getAttribute('data-filter'));
      }
    });
  });

  if (search && searchResults && window.SimpleJekyllSearch) {
    var emptyTemplate = '<p class="search-empty">No matches found.</p>';
    window.SimpleJekyllSearch({
      searchInput: search,
      resultsContainer: searchResults,
      json: '/search.json',
      searchResultTemplate:
        '<a class="card" href="{url}">' +
        '<h2>{title}</h2>' +
        '<p>{author}</p>' +
        '<p class="card-subjects">{subjects}</p>' +
        '</a>',
      noResultsText: emptyTemplate,
      limit: 24,
      fuzzy: false
    });

    search.addEventListener('input', function () {
      var hasQuery = Boolean(search.value.trim());
      if (hasQuery) {
        grid.hidden = true;
        searchResults.hidden = false;
      } else {
        searchResults.hidden = true;
        grid.hidden = false;
        applyFilter(activeFilter());
      }
    });
  }

  applyFilter('read');
})();
