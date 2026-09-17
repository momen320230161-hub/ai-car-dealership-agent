(() => {
  document.querySelectorAll(".brand-mark svg, .chat-app-brand-mark svg").forEach((svg) => {
    svg.setAttribute("width", "22");
    svg.setAttribute("height", "22");
    svg.style.width = "22px";
    svg.style.height = "22px";
    svg.style.maxWidth = "22px";
    svg.style.maxHeight = "22px";
  });

  function readCookie(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    for (const part of document.cookie.split(";")) {
      const trimmed = part.trim();
      if (trimmed.startsWith(prefix)) {
        return decodeURIComponent(trimmed.slice(prefix.length));
      }
    }
    return "";
  }

  const csrfToken = readCookie("autodrive_csrf");
  if (csrfToken) {
    document.querySelectorAll('form[action$="/auth/logout"][method="POST"]').forEach((form) => {
      if (form.querySelector('input[name="csrf_token"]')) return;
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = "csrf_token";
      input.value = csrfToken;
      form.appendChild(input);
    });
  }

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
