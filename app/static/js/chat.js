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

  const ordinalArabic = { 1: "الأولى", 2: "التانية", 3: "التالتة" };
  const pendingLabels = {
    test_drive: "حجز تجربة قيادة (Test Drive)",
    cancel_test_drive: "إلغاء حجز تجربة قيادة",
    sales_lead: "طلب تواصل مبيعات",
  };
  const pendingHints = {
    test_drive: "اكتب باقي البيانات المطلوبة (الاسم، الموبايل، اليوم والوقت) لإتمام التسجيل.",
    cancel_test_drive: "اكتب رقم الطلب المُراد إلغاؤه.",
    sales_lead: "اكتب الاسم ورقم الموبايل ليصلك اتصال من فريق المبيعات.",
  };

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

  function csrfHeaders(extra = {}) {
    const headers = { ...extra };
    if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
    return headers;
  }

  function scrollBottom() {
    requestAnimationFrame(() => { chatWindow.scrollTop = chatWindow.scrollHeight; });
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

  function formatCondition(cond) {
    if (cond === "new") return "جديدة";
    if (cond === "used") return "مستعملة";
    return cond || "";
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

      const card = document.createElement("div");
      card.className = "rec-card flex flex-col justify-between";

      const topArea = document.createElement("div");

      const placeholderBg = document.createElement("div");
      placeholderBg.className = "vehicle-placeholder-bg";
      placeholderBg.innerHTML = `
        <svg class="w-12 h-12 text-[#94A3B8] opacity-75" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M8 17a2 2 0 100 4 2 2 0 000-4zm8 0a2 2 0 100 4 2 2 0 000-4zM3 9l2-4h10l2 4M3 9h18v7a1 1 0 01-1 1H4a1 1 0 01-1-1V9z"/>
        </svg>
      `;
      const badge = document.createElement("span");
      badge.className = "absolute top-2 right-2 bg-[#0F1B33] text-white text-[10px] font-bold px-2 py-0.5 rounded-full";
      badge.textContent = `#${position}`;
      placeholderBg.appendChild(badge);
      topArea.appendChild(placeholderBg);

      const title = document.createElement("h3");
      title.className = "font-bold text-sm text-[#0F1B33] leading-tight";
      title.textContent = [car.brand, car.model].filter(Boolean).join(" ") || "سيارة مسجلة";
      topArea.appendChild(title);

      const specs = document.createElement("div");
      specs.className = "flex items-center gap-1.5 text-[11px] text-[#64748B] mt-1";
      const conditionStr = formatCondition(car.condition);
      const specItems = [car.year, conditionStr, car.body_type].filter(Boolean);
      specs.textContent = specItems.join(" · ");
      topArea.appendChild(specs);

      if (car.price_egp) {
        const price = document.createElement("div");
        price.className = "text-sm font-bold text-[#2F5BD3] mt-2";
        price.textContent = formatPrice(car.price_egp);
        topArea.appendChild(price);
      }

      card.appendChild(topArea);

      const actions = document.createElement("div");
      actions.className = "flex items-center gap-1.5 mt-3 pt-3 border-t border-[#D9E2EF]";

      const detailBtn = document.createElement("button");
      detailBtn.type = "button";
      detailBtn.className = "flex-1 py-1 px-2 bg-[#F1F5F9] hover:bg-[#E2E8F0] text-[#0F1B33] text-[11px] font-medium rounded text-center transition-colors";
      detailBtn.textContent = "التفاصيل";
      detailBtn.dataset.action = "details";
      detailBtn.dataset.position = position;

      const selectBtn = document.createElement("button");
      selectBtn.type = "button";
      selectBtn.className = "flex-1 py-1 px-2 bg-[#2F5BD3] hover:bg-[#2563EB] text-white text-[11px] font-medium rounded text-center transition-colors";
      selectBtn.textContent = "اختر هذه";
      selectBtn.dataset.action = "select";
      selectBtn.dataset.position = position;

      actions.append(detailBtn, selectBtn);
      card.appendChild(actions);

      recommendationGrid.appendChild(card);
    }
    recommendationSection.classList.remove("hidden");
  }

  function renderSelectedCar(selected) {
    if (!selectedContainer) return;
    selectedContainer.replaceChildren();

    if (selected && selected.brand) {
      const wrapper = document.createElement("div");
      wrapper.className = "flex flex-col gap-1";

      const title = document.createElement("span");
      title.className = "text-base font-bold text-[#0F1B33]";
      title.textContent = [selected.brand, selected.model].filter(Boolean).join(" ");
      wrapper.appendChild(title);

      const specs = document.createElement("div");
      specs.className = "flex items-center gap-2 text-xs text-[#64748B] mt-1";
      if (selected.year) {
        const year = document.createElement("span");
        year.className = "bg-[#F1F5F9] px-2 py-0.5 rounded font-medium";
        year.textContent = String(selected.year);
        specs.appendChild(year);
      }
      if (selected.condition) {
        const condition = document.createElement("span");
        condition.className = "bg-[#F1F5F9] px-2 py-0.5 rounded font-medium";
        condition.textContent = formatCondition(selected.condition);
        specs.appendChild(condition);
      }
      wrapper.appendChild(specs);

      if (selected.price_egp) {
        const price = document.createElement("span");
        price.className = "text-sm font-bold text-[#2F5BD3] mt-2";
        price.textContent = formatPrice(selected.price_egp);
        wrapper.appendChild(price);
      }
      selectedContainer.appendChild(wrapper);
      return;
    }

    const empty = document.createElement("div");
    empty.className = "py-2 text-center text-xs text-[#64748B]";
    empty.append("لم يتم تحديد سيارة بعد.", document.createElement("br"));
    empty.append("تصفح الاختيارات واذكر اسم العربية أو رقمها لتحديدها.");
    selectedContainer.appendChild(empty);
  }

  function renderState(state) {
    if (!state || typeof state !== "object") return;
    renderSelectedCar(state.selected_car);
    if (pendingLabel) {
      pendingLabel.textContent = pendingLabels[state.pending_action_type] || "لا يوجد طلب جارٍ تنفيذ بياناته";
    }
    if (pendingHint) {
      pendingHint.textContent = pendingHints[state.pending_action_type] || "يمكنك طلب حجز تجربة قيادة أو طلب تواصل المبيعات في أي وقت.";
    }
    if (Array.isArray(state.visible_recommendations)) {
      renderRecommendations(state.visible_recommendations);
    }
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
        headers: csrfHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
        body: JSON.stringify({ message }),
        signal: controller.signal,
      });
      const payload = await parseJson(response);
      if (payload && typeof payload.response === "string" && payload.response.trim()) {
        addMessage("assistant", payload.response);
      }
      if (payload && payload.state) {
        renderState(payload.state);
      }
      if (payload && Array.isArray(payload.visible_recommendations) && payload.visible_recommendations.length) {
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

  async function refreshHistory() {
    if (!historyUrl || !historyList) return;
    try {
      const response = await fetch(historyUrl, { headers: { Accept: "application/json" } });
      const payload = await parseJson(response);
      if (!response.ok || !payload || !payload.ok || !Array.isArray(payload.conversations)) return;
      historyList.replaceChildren();
      if (payload.conversations.length === 0) {
        const empty = document.createElement("span");
        empty.className = "text-xs text-[#64748B] py-2 text-center";
        empty.textContent = "لا توجد محادثات سابقة";
        historyList.appendChild(empty);
        return;
      }
      for (const item of payload.conversations) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "w-full text-right p-2 text-xs rounded-xl hover:bg-[#F1F5F9] transition-colors border border-transparent flex flex-col gap-0.5 text-[#0F1B33]";
        btn.dataset.historyId = item.id;
        const titleSpan = document.createElement("span");
        titleSpan.className = "truncate w-full";
        titleSpan.textContent = item.title;
        btn.appendChild(titleSpan);
        historyList.appendChild(btn);
      }
    } catch {}
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
        for (const msg of payload.messages) {
          addMessage(msg.role, msg.content);
        }
      } else {
        addMessage("assistant", "يا هلا بيك في المحادثة المختارة!");
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

  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      if (!sendButton.disabled) submitMessage(button.dataset.prompt || "");
    });
  });

  document.addEventListener("click", (event) => {
    const historyBtn = event.target.closest("[data-history-id]");
    if (historyBtn && !sendButton.disabled) {
      const historyId = historyBtn.dataset.historyId;
      if (historyId) switchToSession(historyId);
      return;
    }

    const target = event.target.closest("[data-action]");
    if (!target || sendButton.disabled) return;
    const action = target.dataset.action;
    const pos = Number(target.dataset.position || 1);
    const ordName = ordinalArabic[pos] || `رقم ${pos}`;
    if (action === "details") {
      submitMessage(`عايز تفاصيل العربية ${ordName}`);
    } else if (action === "select") {
      submitMessage(`العربية ${ordName} عجبتني`);
    } else if (action === "compare") {
      submitMessage("قارن أول اتنين");
    }
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

  if (mobileToggle) {
    mobileToggle.addEventListener("click", () => sidebar.classList.toggle("open"));
  }

  // A `q` query parameter may be used to prefill the composer, but it must
  // never trigger a request automatically. Auto-submitting here caused the
  // typing indicator to appear on page load/new-chat without explicit user input.
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