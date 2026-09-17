(() => {
  function readCookie(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    for (const part of document.cookie.split(";")) {
      const trimmed = part.trim();
      if (trimmed.startsWith(prefix)) return decodeURIComponent(trimmed.slice(prefix.length));
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

  const navToggle = document.getElementById("nav-toggle");
  const primaryNav = document.getElementById("primary-nav");
  if (navToggle && primaryNav) {
    navToggle.addEventListener("click", () => {
      const open = primaryNav.classList.toggle("open");
      navToggle.setAttribute("aria-expanded", String(open));
    });
    primaryNav.addEventListener("click", (event) => {
      if (event.target.closest("a")) {
        primaryNav.classList.remove("open");
        navToggle.setAttribute("aria-expanded", "false");
      }
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
