(() => {
  document.querySelectorAll(".brand-mark svg, .chat-app-brand-mark svg").forEach((svg) => {
    svg.setAttribute("width", "22");
    svg.setAttribute("height", "22");
    svg.style.width = "22px";
    svg.style.height = "22px";
    svg.style.maxWidth = "22px";
    svg.style.maxHeight = "22px";
  });

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
