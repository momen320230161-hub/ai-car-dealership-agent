(() => {
  const searchForm = document.getElementById("assistant-search-form");
  const searchInput = document.getElementById("assistant-search");
  if (searchForm && searchInput) {
    searchForm.addEventListener("submit", (event) => {
      if (!searchInput.value.trim()) {
        event.preventDefault();
        searchInput.focus();
      }
    });
  }
})();
