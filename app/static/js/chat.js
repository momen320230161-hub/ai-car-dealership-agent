(() => {
  const app = document.getElementById("chat-app");
  if (!app) return;

  const sendUrl = app.dataset.sendUrl;
  const sessionUrl = app.dataset.sessionUrl;
  const historyUrl = app.dataset.historyUrl;
  const switchBaseUrl = app.dataset.switchBaseUrl || "/api/chat/switch_session/";
  const maxMessageLength = Number(app.dataset.maxMessageLength || 4000);

  const form = document.getElementById("chat-form");
  const input = document.getElementById("chat-input");
  const sendButton = document.getElementById("chat-send");
  const messageList = document.getElementById("message-list");
  const chatWindow = document.getElementById("chat-window");
  const typingRow = document.getElementById("typing-row");
  const errorBox = document.getElementById("chat-error");
  const recommendationSection = document.getElementById("active-recommendations");
  const recommendationGrid = document.getElementById("recommendation-grid");
  const selectedContainer = document.getElementById("selected-car-container");
  const pendingLabel = document.getElementById("pending-action-label");
  const pendingHint = document.getElementById("pending-action-hint");
  const newChatButton = document.getElementById("new-chat-button");
  const historyList = document.getElementById("history-list");
  const mobileToggle = document.getElementById("mobile-side-toggle");
  const sidebar = document.getElementById("chat-sidebar");

  if (!form || !input || !sendButton || !messageList || !chatWindow) return;

  const ordinalArabic = { 1: "الأولى", 2: "التانية", 3: "التالتة" };
  const pendingLabels = {
    test_drive: "حجز تجربة قيادة",
    cancel_test_drive: "إلغاء تجربة قيادة",
    sales_lead: "طلب تواصل مبيعات",
  };
  const pendingHints = {
    test_drive: "كمّل البيانات الناقصة في المحادثة، ومش هيتسجل الطلب قبل اكتمالها.",
    cancel_test_drive: "لو فيه أكتر من طلب نشط، اكتب رقم الطلب المطلوب إلغاؤه.",
    sales_lead: "كمّل الاسم ورقم الموبايل لو لسه ناقصين علشان نسجل طلب التواصل.",
  };

  function readCookie(name) {
    const prefix = `${encodeURIComponent(name)}=`;
    for (const part of document.cookie.split(";")) {
      const trimmed = part.trim();
      if (trimmed.startsWith(prefix)) return decodeURIComponent(trimmed.slice(prefix.length));
    }
    return "";
  }

  function csrfHeaders(extra = {}) {
    const headers = { ...extra };
    const token = readCookie("autodrive_csrf");
    if (token) headers["X-CSRF-Token"] = token;
    return headers;
  }

  function scrollBottom() {
    requestAnimationFrame(() => {
      chatWindow.scrollTop = chatWindow.scrollHeight;
    });
  }

  function setBusy(busy) {
    sendButton.disabled = busy;
    input.disabled = busy;
    if (typingRow) typingRow.classList.toggle("hidden", !busy);
    if (busy) scrollBottom();
  }

  function showError(message) {
    if (!errorBox) return;
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
    scrollBottom();
  }

  function clearError() {
    if (!errorBox) return;
    errorBox.textContent = "";
    errorBox.classList.add("hidden");
  }

  function addMessage(role, content) {
    const row = document.createElement("div");
    row.className = `msg-row ${role === "user" ? "user" : "assistant"}`;

    if (role !== "user") {
      const avatar = document.createElement("div");
      avatar.className = "avatar-badge";
      avatar.textContent = "A";
      row.appendChild(avatar);
    }

    const stack = document.createElement("div");
    stack.className = "message-stack";
    const bubble = document.createElement("div");
    bubble.className = role === "user" ? "msg user-msg" : "msg bot";
    bubble.textContent = content;
    stack.appendChild(bubble);
    row.appendChild(stack);
    messageList.appendChild(row);
    scrollBottom();
  }

  function formatPrice(value) {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return "السعر غير مسجل";
    return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(numeric)} ج.م`;
  }

  function formatCondition(value) {
    if (value === "new") return "جديدة";
    if (value === "used") return "مستعملة";
    return value || "";
  }

  function appendMeta(container, value) {
    if (!value) return;
    const item = document.createElement("span");
    item.textContent = String(value);
    container.appendChild(item);
  }

  function renderRecommendations(items) {
    if (!recommendationGrid || !recommendationSection) return;
    recommendationGrid.replaceChildren();

    if (!Array.isArray(items) || items.length === 0) {
      recommendationSection.classList.add("hidden");
      return;
    }

    for (const item of items) {
      const car = item && typeof item.car === "object" ? item.car : {};
      const position = Number(item.position) || 1;
      const card = document.createElement("article");
      card.className = "rec-card";

      const visual = document.createElement("div");
      visual.className = "rec-visual";
      const badge = document.createElement("span");
      badge.className = "rec-position";
      badge.textContent = `#${position}`;
      const glyph = document.createElement("span");
      glyph.className = "rec-car-icon";
      glyph.textContent = "⌁";
      visual.append(badge, glyph);

      const content = document.createElement("div");
      content.className = "rec-content";
      const title = document.createElement("h3");
      title.textContent = [car.brand, car.model].filter(Boolean).join(" ") || "سيارة مسجلة";
      const meta = document.createElement("div");
      meta.className = "rec-meta";
      appendMeta(meta, car.year);
      appendMeta(meta, formatCondition(car.condition));
      appendMeta(meta, car.body_type);
      content.append(title, meta);
      if (car.price_egp !== null && car.price_egp !== undefined) {
        const price = document.createElement("strong");
        price.className = "rec-price";
        price.textContent = formatPrice(car.price_egp);
        content.appendChild(price);
      }

      const actions = document.createElement("div");
      actions.className = "rec-actions";
      const details = document.createElement("button");
      details.type = "button";
      details.className = "rec-action secondary";
      details.dataset.action = "details";
      details.dataset.position = String(position);
      details.textContent = "التفاصيل";
      const select = document.createElement("button");
      select.type = "button";
      select.className = "rec-action primary";
      select.dataset.action = "select";
      select.dataset.position = String(position);
      select.textContent = "اختار دي";
      actions.append(details, select);

      card.append(visual, content, actions);
      recommendationGrid.appendChild(card);
    }
    recommendationSection.classList.remove("hidden");
  }

  function renderSelectedCar(selected) {
    if (!selectedContainer) return;
    selectedContainer.replaceChildren();

    if (!selected || !selected.brand) {
      const empty = document.createElement("div");
      empty.className = "sidebar-empty";
      empty.textContent = "لسه ما اخترتش عربية. اختار من القائمة أو اذكر اسمها.";
      selectedContainer.appendChild(empty);
      return;
    }

    const wrapper = document.createElement("div");
    wrapper.className = "selected-car-summary";
    const title = document.createElement("strong");
    title.textContent = [selected.brand, selected.model].filter(Boolean).join(" ");
    const meta = document.createElement("div");
    meta.className = "selected-car-meta";
    appendMeta(meta, selected.year);
    appendMeta(meta, formatCondition(selected.condition));
    wrapper.append(title, meta);
    if (selected.price_egp !== null && selected.price_egp !== undefined) {
      const price = document.createElement("b");
      price.textContent = formatPrice(selected.price_egp);
      wrapper.appendChild(price);
    }
    selectedContainer.appendChild(wrapper);
  }

  function renderState(state) {
    if (!state || typeof state !== "object") return;
    renderSelectedCar(state.selected_car);
    if (pendingLabel) {
      pendingLabel.textContent = pendingLabels[state.pending_action_type] || "مفيش طلب جارٍ";
    }
    if (pendingHint) {
      pendingHint.textContent = pendingHints[state.pending_action_type] || "تقدر تطلب Test Drive أو تواصل من المبيعات في أي وقت.";
    }
    if (Array.isArray(state.visible_recommendations)) renderRecommendations(state.visible_recommendations);
  }

  async function parseJson(response) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  async function submitMessage(rawMessage) {
    const message = String(rawMessage ?? input.value).trim();
    if (!message) {
      showError("اكتب رسالة قبل الإرسال.");
      input.focus();
      return;
    }
    if (message.length > maxMessageLength) {
      showError("الرسالة أطول من الحد المسموح.");
      return;
    }

    clearError();
    addMessage("user", message);
    input.value = "";
    input.style.height = "auto";
    setBusy(true);

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 90000);
    try {
      const response = await fetch(sendUrl, {
        method: "POST",
        headers: csrfHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });
      const payload = await parseJson(response);
      if (payload && typeof payload.response === "string" && payload.response.trim()) {
        addMessage("assistant", payload.response);
      }
      if (payload && payload.state) renderState(payload.state);
      if (payload && Array.isArray(payload.visible_recommendations)) {
        renderRecommendations(payload.visible_recommendations);
      }
      if (!response.ok) {
        showError(payload && typeof payload.message === "string" ? payload.message : "حصلت مشكلة مؤقتة. جرّب تاني بعد لحظات.");
      } else {
        refreshHistory();
      }
    } catch (error) {
      showError(error && error.name === "AbortError" ? "الرد أخد وقت أطول من المتوقع. تقدر تعيد المحاولة." : "تعذر الاتصال بالخدمة. جرّب تاني بعد لحظات.");
    } finally {
      window.clearTimeout(timeout);
      setBusy(false);
      input.focus();
      scrollBottom();
    }
  }

  async function refreshHistory() {
    if (!historyUrl || !historyList) return;
    try {
      const response = await fetch(historyUrl, { headers: { Accept: "application/json" } });
      const payload = await parseJson(response);
      if (!response.ok || !payload || !payload.ok || !Array.isArray(payload.conversations)) return;
      historyList.replaceChildren();
      if (payload.conversations.length === 0) {
        const empty = document.createElement("span");
        empty.className = "sidebar-empty";
        empty.textContent = "لا توجد محادثات سابقة";
        historyList.appendChild(empty);
        return;
      }
      for (const item of payload.conversations) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "history-item";
        button.dataset.historyId = item.id;
        const icon = document.createElement("span");
        icon.className = "history-icon";
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = "◫";
        const title = document.createElement("span");
        title.className = "history-title";
        title.textContent = item.title;
        button.append(icon, title);
        historyList.appendChild(button);
      }
    } catch {
      // History refresh is a non-blocking enhancement.
    }
  }

  async function switchToSession(sessionId) {
    if (!sessionId || sendButton.disabled) return;
    clearError();
    setBusy(true);
    try {
      const response = await fetch(`${switchBaseUrl}${sessionId}`, {
        method: "POST",
        headers: csrfHeaders({ Accept: "application/json" }),
      });
      const payload = await parseJson(response);
      if (!response.ok || !payload || !payload.ok) throw new Error("switch failed");
      messageList.replaceChildren();
      if (Array.isArray(payload.messages) && payload.messages.length) {
        for (const message of payload.messages) addMessage(message.role, message.content);
      } else {
        addMessage("assistant", "أهلاً بيك في المحادثة دي. نكمّل من هنا.");
      }
      renderRecommendations([]);
      renderState(payload.state);
      refreshHistory();
      if (sidebar) sidebar.classList.remove("open");
    } catch {
      showError("تعذر الانتقال للمحادثة. جرّب تاني بعد لحظات.");
    } finally {
      setBusy(false);
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!sendButton.disabled) submitMessage();
  });

  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!sendButton.disabled) submitMessage();
    }
  });

  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
    clearError();
  });

  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!sendButton.disabled) submitMessage(button.dataset.prompt || "");
    });
  });

  document.addEventListener("click", (event) => {
    const historyButton = event.target.closest("[data-history-id]");
    if (historyButton && !sendButton.disabled) {
      switchToSession(historyButton.dataset.historyId);
      return;
    }

    const actionButton = event.target.closest("[data-action]");
    if (!actionButton || sendButton.disabled) return;
    const action = actionButton.dataset.action;
    const position = Number(actionButton.dataset.position || 1);
    const ordinal = ordinalArabic[position] || `رقم ${position}`;
    if (action === "details") submitMessage(`عايز تفاصيل العربية ${ordinal}`);
    if (action === "select") submitMessage(`العربية ${ordinal} عجبتني`);
    if (action === "compare") submitMessage("قارن أول اتنين");
  });

  if (newChatButton) {
    newChatButton.addEventListener("click", async () => {
      if (sendButton.disabled) return;
      clearError();
      setBusy(true);
      try {
        const response = await fetch(sessionUrl, {
          method: "POST",
          headers: csrfHeaders({ Accept: "application/json" }),
        });
        const payload = await parseJson(response);
        if (!response.ok || !payload || !payload.ok) throw new Error("session reset failed");
        messageList.replaceChildren();
        renderRecommendations([]);
        renderState(payload.state);
        addMessage("assistant", "بدأنا محادثة جديدة. قولّي بتدور على عربية بإيه، وأنا أساعدك حسب البيانات المتاحة.");
        refreshHistory();
        if (sidebar) sidebar.classList.remove("open");
      } catch {
        showError("تعذر بدء محادثة جديدة دلوقتي. جرّب تاني بعد لحظات.");
      } finally {
        setBusy(false);
      }
    });
  }

  if (mobileToggle && sidebar) {
    mobileToggle.addEventListener("click", () => sidebar.classList.toggle("open"));
  }

  const query = new URLSearchParams(window.location.search).get("q");
  if (query && query.trim()) {
    input.value = query.trim();
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
    const cleanUrl = `${window.location.pathname}${window.location.hash || ""}`;
    window.history.replaceState({}, "", cleanUrl);
  }

  scrollBottom();
})();
