let modalTrigger = null;
let dashboardCharts = [];

function openModal() {
  const modal = document.getElementById("modal");
  if (modal && modal.innerHTML.trim()) {
    const wasOpen = modal.classList.contains("flex");
    if (!wasOpen) modalTrigger = document.activeElement;
    const heading = modal.querySelector("h1, h2, h3");
    if (heading) {
      if (!heading.id) heading.id = "active-modal-title";
      modal.setAttribute("aria-labelledby", heading.id);
    }
    modal.setAttribute("aria-hidden", "false");
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    document.body.style.overflow = "hidden";
    window.requestAnimationFrame(() => {
      const invalidField = modal.querySelector('[aria-invalid="true"]');
      (invalidField || modal).focus();
    });
  }
}

function closeModal() {
  const modal = document.getElementById("modal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    modal.setAttribute("aria-hidden", "true");
    modal.removeAttribute("aria-labelledby");
    modal.innerHTML = "";
    document.body.style.overflow = "";
    if (modalTrigger instanceof HTMLElement && document.contains(modalTrigger)) {
      modalTrigger.focus();
    }
    modalTrigger = null;
  }
}

function trapModalFocus(event) {
  const modal = document.getElementById("modal");
  if (!modal?.classList.contains("flex") || event.key !== "Tab") return;
  const focusable = [...modal.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')]
    .filter((element) => !element.hidden && element.offsetParent !== null);
  if (!focusable.length) {
    event.preventDefault();
    modal.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function applyStoredTheme() {
  let theme = "light";
  try {
    theme = localStorage.getItem("gastou-lembrou-theme") || "light";
  } catch (error) {}
  document.documentElement.dataset.theme = theme === "dark" ? "dark" : "light";
  updateThemeToggle();
}

function toggleTheme() {
  const isDark = document.documentElement.dataset.theme === "dark";
  const nextTheme = isDark ? "light" : "dark";
  document.documentElement.dataset.theme = nextTheme;
  try {
    localStorage.setItem("gastou-lembrou-theme", nextTheme);
  } catch (error) {}
  updateThemeToggle();
  if (document.getElementById("categoryChart")) renderDashboardCharts();
}

function updateThemeToggle() {
  const isDark = document.documentElement.dataset.theme === "dark";
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    const icon = button.querySelector("[data-theme-icon]");
    const label = button.querySelector("[data-theme-label]");
    button.setAttribute("aria-label", isDark ? "Alternar para modo claro" : "Alternar para modo escuro");
    button.setAttribute("title", isDark ? "Modo claro" : "Modo escuro");
    if (icon) {
      icon.classList.toggle("fa-sun", isDark);
      icon.classList.toggle("fa-moon", !isDark);
    }
    if (label) label.textContent = isDark ? "Modo claro" : "Modo escuro";
  });
}

function renderDashboardCharts() {
  const categoryCanvas = document.getElementById("categoryChart");
  const monthCanvas = document.getElementById("monthChart");
  const paymentMethodCanvas = document.getElementById("paymentMethodChart");
  if (!categoryCanvas || !monthCanvas || !window.Chart) return;

  const categoryLabels = JSON.parse(document.getElementById("category-labels").textContent);
  const categoryTotals = JSON.parse(document.getElementById("category-totals").textContent);
  const monthLabels = JSON.parse(document.getElementById("month-labels").textContent);
  const monthTotals = JSON.parse(document.getElementById("month-totals").textContent);
  const paymentMethodLabels = JSON.parse(document.getElementById("payment-method-labels").textContent);
  const paymentMethodTotals = JSON.parse(document.getElementById("payment-method-totals").textContent);
  dashboardCharts.forEach((chart) => chart.destroy());
  dashboardCharts = [];
  const styles = getComputedStyle(document.body);
  const chartText = styles.getPropertyValue("--workspace-text-soft").trim() || "#586963";
  const chartGrid = styles.getPropertyValue("--workspace-border").trim() || "#dce7e2";
  const chartSurface = styles.getPropertyValue("--workspace-surface").trim() || "#ffffff";
  const chartBrand = styles.getPropertyValue("--workspace-brand").trim() || "#0d6b5a";
  const chartPalette = [
    "#047857", 
    "#0284c7", 
    "#d97706", 
    "#7c3aed", 
    "#dc2626", 
    "#475569", 
    "#3508b2",
    "#b2087f",
    "#089eb2",
    "#e9e8ee",
    "#08b22d",
    "#8db208",
    "#8208b2",
  ];
  const legendOptions = {
    labels: {
      color: chartText,
      boxWidth: 12,
      boxHeight: 12,
      usePointStyle: true,
      padding: 16,
      font: { family: "Manrope", size: 11, weight: 600 },
    },
  };
  const currencyFormatter = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  const percentFormatter = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  function chartMode(canvas) {
    return canvas.closest("[data-chart-panel]")?.dataset.chartMode || "currency";
  }

  function chartValues(values, mode) {
    if (mode !== "percent") return values;
    const total = values.reduce((sum, value) => sum + Number(value || 0), 0);
    if (!total) return values.map(() => 0);
    return values.map((value) => (Number(value || 0) / total) * 100);
  }

  function doughnutTooltip(rawValues, mode) {
    return {
      callbacks: {
        label(context) {
          const label = context.label || "";
          const rawValue = Number(rawValues[context.dataIndex] || 0);
          const total = rawValues.reduce((sum, value) => sum + Number(value || 0), 0);
          if (mode === "percent") {
            const percent = total ? (rawValue / total) * 100 : 0;
            return `${label}: ${percentFormatter.format(percent)}%`;
          }
          return `${label}: ${currencyFormatter.format(rawValue)}`;
        },
      },
    };
  }

  updateChartToggleStates();
  const categoryMode = chartMode(categoryCanvas);
  const paymentMethodMode = paymentMethodCanvas ? chartMode(paymentMethodCanvas) : "currency";

  dashboardCharts.push(new Chart(categoryCanvas, {
    type: "doughnut",
    data: {
      labels: categoryLabels,
      datasets: [{ label: categoryMode === "percent" ? "Percentual" : "Total", data: chartValues(categoryTotals, categoryMode), backgroundColor: chartPalette, borderColor: chartSurface, borderWidth: 3 }],
    },
    options: { maintainAspectRatio: false, plugins: { legend: legendOptions, tooltip: doughnutTooltip(categoryTotals, categoryMode) } },
  }));

  dashboardCharts.push(new Chart(monthCanvas, {
    type: "line",
    data: {
      labels: monthLabels,
      datasets: [{ label: "Gastos", data: monthTotals, borderColor: chartBrand, backgroundColor: chartBrand, tension: 0.35, pointRadius: 3, pointHoverRadius: 5 }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: legendOptions },
      scales: {
        x: { ticks: { color: chartText, font: { family: "Manrope", size: 11 } }, grid: { color: chartGrid } },
        y: { beginAtZero: true, ticks: { color: chartText, font: { family: "Manrope", size: 11 } }, grid: { color: chartGrid } },
      },
    },
  }));

  if (paymentMethodCanvas) {
    dashboardCharts.push(new Chart(paymentMethodCanvas, {
      type: "doughnut",
      data: {
        labels: paymentMethodLabels,
        datasets: [{ label: paymentMethodMode === "percent" ? "Percentual" : "Total", data: chartValues(paymentMethodTotals, paymentMethodMode), backgroundColor: chartPalette, borderColor: chartSurface, borderWidth: 3 }],
      },
      options: { maintainAspectRatio: false, plugins: { legend: legendOptions, tooltip: doughnutTooltip(paymentMethodTotals, paymentMethodMode) } },
    }));
  }
}

function updateChartToggleStates(root = document) {
  root.querySelectorAll("[data-chart-panel]").forEach((panel) => {
    const mode = panel.dataset.chartMode || "currency";
    panel.querySelectorAll("[data-chart-toggle]").forEach((button) => {
      const isActive = button.dataset.chartToggle === mode;
      button.classList.toggle("is-active", isActive);
      button.setAttribute("aria-pressed", String(isActive));
    });
  });
}

function initPhoneInputs(root = document) {
  if (!window.intlTelInput) return;
  root.querySelectorAll("[data-intl-phone]").forEach((input) => {
    if (input.dataset.intlPhoneReady === "true") return;
    const iti = window.intlTelInput(input, {
      initialCountry: "br",
      preferredCountries: ["br", "us", "pt", "ar", "cl", "uy"],
      separateDialCode: true,
      nationalMode: false,
      formatAsYouType: true,
      utilsScript: "https://cdn.jsdelivr.net/npm/intl-tel-input@23.8.1/build/js/utils.js",
    });
    input.phoneInputInstance = iti;
    input.dataset.intlPhoneReady = "true";
    enforcePhoneDigitLimit(input);
    updatePhoneFeedback(input);
    input.addEventListener("countrychange", () => {
      enforcePhoneDigitLimit(input);
      updatePhoneFeedback(input);
    });
    input.form?.addEventListener("submit", () => {
      if (input.value.trim()) {
        input.value = iti.getNumber();
      }
    });
  });
}

function phoneDigits(input) {
  return (input.value || "").replace(/\D/g, "");
}

function maxNationalPhoneDigits(input) {
  const dialCode = input.phoneInputInstance?.getSelectedCountryData()?.dialCode || "55";
  return Math.max(4, 15 - dialCode.length);
}

function nationalPhoneDigitRange(input) {
  const country = input.phoneInputInstance?.getSelectedCountryData()?.iso2;
  if (country === "br") return { min: 10, max: 11 };
  const max = maxNationalPhoneDigits(input);
  return { min: 4, max };
}

function enforcePhoneDigitLimit(input) {
  if (!input.matches("[data-phone-limit]")) return;
  const digits = phoneDigits(input);
  const { max: maxDigits } = nationalPhoneDigitRange(input);
  if (digits.length <= maxDigits) return;
  input.value = digits.slice(0, maxDigits);
}

function updatePhoneFeedback(input) {
  const feedback = input.closest("label")?.querySelector("[data-phone-feedback]");
  if (!feedback) return;
  const digits = phoneDigits(input);
  const { min: minDigits, max: maxDigits } = nationalPhoneDigitRange(input);
  const isEmpty = digits.length === 0;
  const hasExpectedLength = digits.length >= minDigits && digits.length <= maxDigits;
  const isValid = Boolean(input.phoneInputInstance?.isValidNumber()) || hasExpectedLength;

  feedback.classList.remove("text-slate-500", "text-red-700", "text-emerald-700");
  input.classList.remove("border-red-300", "border-emerald-300");

  if (isEmpty) {
    feedback.textContent = "Digite um telefone válido.";
    feedback.classList.add("text-slate-500");
  } else if (isValid) {
    feedback.textContent = "Telefone válido.";
    feedback.classList.add("text-emerald-700");
    input.classList.add("border-emerald-300");
  } else {
    feedback.textContent = minDigits === maxDigits
      ? `Informe o telefone com ${maxDigits} dígitos, sem contar o código do país.`
      : `Informe o telefone com ${minDigits} a ${maxDigits} dígitos, sem contar o código do país.`;
    feedback.classList.add("text-red-700");
    input.classList.add("border-red-300");
  }
}

function isValidCpf(value) {
  const cpf = (value || "").replace(/\D/g, "");
  if (!cpf) return null;
  if (cpf.length !== 11 || /^(\d)\1{10}$/.test(cpf)) return false;

  for (const size of [9, 10]) {
    let total = 0;
    for (let index = 0; index < size; index += 1) {
      total += Number(cpf[index]) * ((size + 1) - index);
    }
    let digit = (total * 10) % 11;
    digit = digit === 10 ? 0 : digit;
    if (digit !== Number(cpf[size])) return false;
  }
  return true;
}

function formatCpf(value) {
  const digits = (value || "").replace(/\D/g, "").slice(0, 11);
  return digits
    .replace(/^(\d{3})(\d)/, "$1.$2")
    .replace(/^(\d{3})\.(\d{3})(\d)/, "$1.$2.$3")
    .replace(/^(\d{3})\.(\d{3})\.(\d{3})(\d)/, "$1.$2.$3-$4");
}

function updateCpfFeedback(input) {
  const feedback = input.closest("label")?.querySelector("[data-cpf-feedback]");
  if (!feedback) return;
  const validity = isValidCpf(input.value);
  feedback.classList.remove("text-slate-500", "text-red-700", "text-emerald-700");
  input.classList.remove("border-red-300", "border-emerald-300");

  if (validity === null) {
    feedback.textContent = "Digite um CPF válido.";
    feedback.classList.add("text-slate-500");
  } else if (validity) {
    feedback.textContent = "CPF válido.";
    feedback.classList.add("text-emerald-700");
    input.classList.add("border-emerald-300");
  } else {
    feedback.textContent = "CPF inválido.";
    feedback.classList.add("text-red-700");
    input.classList.add("border-red-300");
  }
}

function updateClearableFilter(input) {
  const wrapper = input.closest(".clearable-filter-field");
  if (!wrapper) return;
  wrapper.classList.toggle("has-value", Boolean(input.value));
}

function initClearableFilters(root = document) {
  root.querySelectorAll(".clearable-filter-input").forEach(updateClearableFilter);
}

function formatCurrencyFromDigits(value, options = {}) {
  const digits = (value || "").replace(/\D/g, "");
  if (!digits) return "";
  const cents = Number(digits) / 100;
  if (options.withSymbol) {
    return cents.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
  }
  return cents.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function initCurrencyCentInputs(root = document) {
  root.querySelectorAll("[data-currency-cents]").forEach((input) => {
    if (input.value) input.value = formatCurrencyFromDigits(input.value, { withSymbol: !input.closest(".currency-field") });
  });
}

function normalizeText(value) {
  return (value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

function isCreditCardMethodLabel(value) {
  return ["cartao de credito", "cartao credito", "credito"].includes(normalizeText(value));
}

function updateInstallmentField(select) {
  const form = select.closest("form");
  const field = form?.querySelector("[data-installment-field]");
  if (!field) return;
  const selectedLabel = select.options[select.selectedIndex]?.text || "";
  const shouldShow = isCreditCardMethodLabel(selectedLabel);
  field.classList.toggle("is-hidden", !shouldShow);
  field.querySelector("input[type='checkbox']")?.toggleAttribute("disabled", !shouldShow);
  if (!shouldShow) {
    const checkbox = field.querySelector("input[type='checkbox']");
    if (checkbox) checkbox.checked = false;
  }
}

function initInstallmentFields(root = document) {
  root.querySelectorAll("[data-payment-method-select]").forEach(updateInstallmentField);
}

function registerPwaServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  const isLocalhost = ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
  if (!window.isSecureContext && !isLocalhost) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => {});
  });
}

document.addEventListener("DOMContentLoaded", () => {
  applyStoredTheme();
  initPhoneInputs();
  document.querySelectorAll("[data-cpf-mask]").forEach(updateCpfFeedback);
  initClearableFilters();
  initCurrencyCentInputs();
  initInstallmentFields();
  registerPwaServiceWorker();
});

document.body.addEventListener("htmx:afterSwap", (event) => {
  if (event.detail.target.id === "modal") openModal();
  initPhoneInputs(event.detail.target);
  initCurrencyCentInputs(event.detail.target);
  initInstallmentFields(event.detail.target);
});

document.body.addEventListener("click", (event) => {
  if (event.target.closest("[data-close-modal]") || event.target.id === "modal") closeModal();
  const clearFilterButton = event.target.closest("[data-clear-filter]");
  if (clearFilterButton) {
    const input = clearFilterButton.closest(".clearable-filter-field")?.querySelector("input");
    if (input) {
      input.value = "";
      updateClearableFilter(input);
      input.focus();
    }
  }
  const activeFilterButton = event.target.closest("[data-clear-filter-name]");
  if (activeFilterButton) {
    const form = activeFilterButton.closest("form");
    const field = form?.elements.namedItem(activeFilterButton.dataset.clearFilterName);
    if (field) {
      field.value = activeFilterButton.dataset.defaultValue || "";
      form.requestSubmit();
    }
  }
  const sidebarToggle = event.target.closest("[data-sidebar-toggle]");
  if (sidebarToggle) {
    const sidebar = document.querySelector("[data-sidebar]");
    const isCollapsed = sidebar?.classList.toggle("collapsed");
    const arrow = sidebarToggle.querySelector("[data-sidebar-arrow]");
    if (arrow) {
      arrow.classList.toggle("fa-chevron-right", Boolean(isCollapsed));
      arrow.classList.toggle("fa-chevron-left", !isCollapsed);
    }
    sidebarToggle.setAttribute("aria-expanded", String(!isCollapsed));
    sidebarToggle.setAttribute("aria-label", isCollapsed ? "Expandir sidebar" : "Encolher sidebar");
    sidebarToggle.setAttribute("title", isCollapsed ? "Expandir sidebar" : "Encolher sidebar");
  }
  const passwordToggle = event.target.closest("[data-toggle-password]");
  if (passwordToggle) {
    const input = passwordToggle.closest(".password-wrap")?.querySelector("input");
    if (input) {
      const willShow = input.type === "password";
      input.type = willShow ? "text" : "password";
      passwordToggle.setAttribute("aria-label", willShow ? "Ocultar senha" : "Mostrar senha");
      passwordToggle.setAttribute("title", willShow ? "Ocultar senha" : "Mostrar senha");
      const icon = passwordToggle.querySelector("i");
      if (icon) {
        icon.classList.toggle("fa-eye", !willShow);
        icon.classList.toggle("fa-eye-slash", willShow);
      }
    }
  }
  if (event.target.closest("[data-theme-toggle]")) {
    toggleTheme();
  }
  const chartToggle = event.target.closest("[data-chart-toggle]");
  if (chartToggle) {
    const panel = chartToggle.closest("[data-chart-panel]");
    if (panel) {
      panel.dataset.chartMode = chartToggle.dataset.chartToggle;
      updateChartToggleStates(panel);
      renderDashboardCharts();
    }
  }
});

document.addEventListener("keydown", (event) => {
  const modal = document.getElementById("modal");
  if (event.key === "Escape" && modal?.classList.contains("flex")) {
    event.preventDefault();
    closeModal();
    return;
  }
  trapModalFocus(event);
});

document.body.addEventListener("input", (event) => {
  if (event.target.matches(".clearable-filter-input")) {
    updateClearableFilter(event.target);
  }
  if (event.target.matches("[data-cpf-mask]")) {
    event.target.value = formatCpf(event.target.value);
    updateCpfFeedback(event.target);
    return;
  }
  if (event.target.matches("[data-phone-limit]")) {
    enforcePhoneDigitLimit(event.target);
    updatePhoneFeedback(event.target);
  }
  if (event.target.matches("[data-currency-cents]")) {
    event.target.value = formatCurrencyFromDigits(event.target.value, { withSymbol: !event.target.closest(".currency-field") });
    return;
  }
  if (!event.target.matches("[data-phone-mask]")) return;
  const digits = event.target.value.replace(/\D/g, "").slice(0, 11);
  const ddd = digits.slice(0, 2);
  const first = digits.slice(2, 7);
  const last = digits.slice(7, 11);
  event.target.value = digits.length > 7 ? `(${ddd}) ${first}-${last}` : digits.length > 2 ? `(${ddd}) ${first}` : digits;
});

document.body.addEventListener("change", (event) => {
  if (event.target.matches("[data-payment-method-select]")) {
    updateInstallmentField(event.target);
  }
});
