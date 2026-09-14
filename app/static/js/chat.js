(() => {
  const app = document.getElementById("chat-app");
  if (!app) return;

  const sendUrl = app.dataset.sendUrl;
  const sessionUrl = app.dataset.sessionUrl;
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
  const selectedLabel = document.getElementById("selected-car-label");
  const pendingLabel = document.getElementById("pending-action-label");
  const newChatButton = document.getElementById("new-chat-button");
  const mobileToggle = document.getElementById("mobile-side-toggle");
  const sidebar = document.getElementById("chat-sidebar");

  const pendingLabels = {
    test_drive: "تجربة قيادة",
    cancel_test_drive: "إلغاء تجربة قيادة",
    sales_lead: "تواصل مبيعات",
  };

  function scrollBottom() {
    requestAnimationFrame(() => { chatWindow.scrollTop = chatWindow.scrollHeight; });
  }

  function setBusy(busy) {
    sendButton.disabled = busy;
    input.disabled = busy;
    typingRow.classList.toggle("hidden", !busy);
    if (busy) scrollBottom();
  }

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.remove("hidden");
    scrollBottom();
  }

  function clearError() {
    errorBox.textContent = "";
    errorBox.classList.add("hidden");
  }

  function addMessage(role, content) {
    const row = document.createElement("div");
    row.className = `msg-row ${role === "user" ? "user" : "assistant"}`;
    if (role !== "user") {
      const avatar = document.createElement("div");
      avatar.className = "avatar small";
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

  function renderRecommendations(items) {
    recommendationGrid.replaceChildren();
    if (!Array.isArray(items) || items.length === 0) {
      recommendationSection.classList.add("hidden");
      return;
    }
    for (const item of items) {
      const car = item && typeof item.car === "object" ? item.car : {};
      const card = document.createElement("a");
      card.className = "recommendation-card";
      if (item.car_id) card.href = `/cars/${encodeURIComponent(item.car_id)}`;

      const position = document.createElement("span");
      position.className = "recommendation-position";
      position.textContent = `#${item.position ?? "—"}`;

      const info = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = [car.brand, car.model].filter(Boolean).join(" ") || "سيارة مسجلة";
      const meta = document.createElement("small");
      const condition = car.condition === "new" ? "جديدة" : car.condition === "used" ? "مستعملة" : null;
      meta.textContent = [car.year, condition, car.body_type].filter(Boolean).join(" · ");
      info.append(title, meta);

      const price = document.createElement("b");
      price.textContent = formatPrice(car.price_egp);
      card.append(position, info, price);
      recommendationGrid.appendChild(card);
    }
    recommendationSection.classList.remove("hidden");
  }

  function renderState(state) {
    if (!state || typeof state !== "object") return;
    const selected = state.selected_car;
    selectedLabel.textContent = selected
      ? [selected.brand, selected.model].filter(Boolean).join(" ") || `#${selected.id}`
      : "لا يوجد";
    pendingLabel.textContent = pendingLabels[state.pending_action_type] || "لا يوجد";
    if (Array.isArray(state.visible_recommendations)) renderRecommendations(state.visible_recommendations);
  }

  async function parseJson(response) {
    try { return await response.json(); } catch { return null; }
  }

  async function submitMessage(rawMessage) {
    const message = String(rawMessage ?? input.value).trim();
    if (!message) { showError("اكتب رسالة قبل الإرسال."); input.focus(); return; }
    if (message.length > maxMessageLength) { showError("الرسالة أطول من الحد المسموح."); return; }

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
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });
      const payload = await parseJson(response);
      if (payload && typeof payload.response === "string" && payload.response.trim()) addMessage("assistant", payload.response);
      if (payload && payload.state) renderState(payload.state);
      if (payload && Array.isArray(payload.visible_recommendations) && payload.visible_recommendations.length) renderRecommendations(payload.visible_recommendations);
      if (!response.ok) {
        showError(payload && typeof payload.message === "string" ? payload.message : "حصلت مشكلة مؤقتة. جرّب تاني بعد لحظات.");
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

  form.addEventListener("submit", (event) => { event.preventDefault(); if (!sendButton.disabled) submitMessage(); });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); if (!sendButton.disabled) submitMessage(); }
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
    clearError();
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => { if (!sendButton.disabled) submitMessage(button.dataset.prompt || ""); });
  });

  newChatButton.addEventListener("click", async () => {
    if (sendButton.disabled) return;
    clearError();
    setBusy(true);
    try {
      const response = await fetch(sessionUrl, { method: "POST", headers: { Accept: "application/json" } });
      const payload = await parseJson(response);
      if (!response.ok || !payload || !payload.ok) throw new Error("session reset failed");
      messageList.replaceChildren();
      renderRecommendations([]);
      renderState(payload.state);
      addMessage("assistant", "بدأنا محادثة جديدة. قولّي بتدور على عربية بإيه، وأنا أساعدك حسب البيانات المتاحة.");
      sidebar.classList.remove("open");
    } catch {
      showError("تعذر بدء محادثة جديدة دلوقتي. جرّب تاني بعد لحظات.");
    } finally { setBusy(false); }
  });

  if (mobileToggle) mobileToggle.addEventListener("click", () => sidebar.classList.toggle("open"));

  const query = new URLSearchParams(window.location.search).get("q");
  if (query && query.trim()) {
    const cleanUrl = `${window.location.pathname}${window.location.hash || ""}`;
    window.history.replaceState({}, "", cleanUrl);
    window.setTimeout(() => submitMessage(query), 180);
  }
  scrollBottom();
})();
