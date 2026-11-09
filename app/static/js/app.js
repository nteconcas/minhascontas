/* =====================================================================
   FinControl — JavaScript principal
   - tema (modo escuro persistido no SQLite via /configuracoes/tema)
   - sidebar mobile, busca rápida, máscara de moeda, confirmações
   - helpers de gráficos (Chart.js) que respeitam o tema atual
   ===================================================================== */
(function () {
  "use strict";

  const html = document.documentElement;
  const APP = window.APP || {};

  /* ---------------------------------------------------------- tema */
  function applyTheme(theme) {
    html.setAttribute("data-bs-theme", theme);
    const icon = document.getElementById("themeIcon");
    if (icon) icon.className = "bi " + (theme === "dark" ? "bi-sun" : "bi-moon-stars");
    document.querySelectorAll("meta[name=theme-color]").forEach((m) => {
      m.setAttribute("content", theme === "dark" ? "#0b1020" : "#4f46e5");
    });
    window.dispatchEvent(new CustomEvent("fc:theme", { detail: theme }));
  }

  function toggleTheme() {
    const next = html.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    applyTheme(next);
    const body = new FormData();
    body.append("theme", next);
    fetch("/configuracoes/tema", {
      method: "POST",
      body,
      headers: { "X-Requested-With": "fetch" },
    }).catch(() => {});
  }

  document.getElementById("themeToggle")?.addEventListener("click", toggleTheme);

  /* ---------------------------------------------------------- sidebar */
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.querySelector(".sidebar-backdrop");
  document.querySelectorAll("[data-sidebar-open]").forEach((btn) =>
    btn.addEventListener("click", () => {
      sidebar?.classList.add("open");
      backdrop?.classList.add("show");
    })
  );
  document.querySelectorAll("[data-sidebar-close]").forEach((btn) =>
    btn.addEventListener("click", () => {
      sidebar?.classList.remove("open");
      backdrop?.classList.remove("show");
    })
  );

  /* ---------------------------------------------------------- confirmações */
  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (ev) => {
      if (!window.confirm(form.dataset.confirm)) ev.preventDefault();
    });
  });

  /* ---------------------------------------------------------- busca rápida */
  const search = document.getElementById("quickSearch");
  const results = document.getElementById("searchResults");
  let searchTimer = null;

  function money(v) {
    return "R$ " + Number(v).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function renderResults(data) {
    if (!results) return;
    const items = [];
    (data.expenses || []).forEach((e) => {
      items.push(`<a class="result-item" href="/despesas/${e.id}/editar">
        <span><i class="bi bi-arrow-up-circle text-danger me-1"></i>${e.description}
        <small class="d-block text-mut ms-4">${e.category} · ${new Date(e.date + "T12:00").toLocaleDateString("pt-BR")}</small></span>
        <span class="amount neg">-${money(e.amount)}</span></a>`);
    });
    (data.incomes || []).forEach((i) => {
      items.push(`<a class="result-item" href="/entradas/${i.id}/editar">
        <span><i class="bi bi-arrow-down-circle text-success me-1"></i>${i.description}
        <small class="d-block text-mut ms-4">${i.category} · ${new Date(i.date + "T12:00").toLocaleDateString("pt-BR")}</small></span>
        <span class="amount pos">${money(i.amount)}</span></a>`);
    });
    results.innerHTML = items.length ? items.join("") : '<div class="empty">Nenhum lançamento encontrado.</div>';
    results.classList.remove("d-none");
  }

  search?.addEventListener("input", () => {
    const q = search.value.trim();
    clearTimeout(searchTimer);
    if (q.length < 2) {
      results?.classList.add("d-none");
      return;
    }
    searchTimer = setTimeout(() => {
      fetch("/api/busca?q=" + encodeURIComponent(q))
        .then((r) => r.json())
        .then(renderResults)
        .catch(() => {});
    }, 220);
  });

  document.addEventListener("click", (ev) => {
    if (results && !results.contains(ev.target) && ev.target !== search) {
      results.classList.add("d-none");
    }
  });

  /* ---------------------------------------------------------- máscara de moeda */
  document.querySelectorAll("input[data-money]").forEach((input) => {
    input.addEventListener("blur", () => {
      const raw = input.value.replace(/[^\d,.-]/g, "").replace(/\./g, "").replace(",", ".");
      const n = parseFloat(raw);
      if (!isNaN(n)) input.value = n.toFixed(2);
    });
  });

  /* ---------------------------------------------------------- Chart.js helpers */
  const PALETTE = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#06b6d4", "#a855f7",
    "#ec4899", "#14b8a6", "#f97316", "#84cc16", "#3b82f6", "#eab308"];

  function isDark() {
    return html.getAttribute("data-bs-theme") === "dark";
  }

  function chartDefaults() {
    if (!window.Chart) return;
    Chart.defaults.font.family = "'Inter','Segoe UI',system-ui,sans-serif";
    Chart.defaults.font.size = 11;
    Chart.defaults.color = isDark() ? "#93a0bd" : "#64748b";
    Chart.defaults.borderColor = isDark() ? "rgba(148,163,184,.14)" : "rgba(100,116,139,.14)";
  }

  function gridColor() {
    return isDark() ? "rgba(148,163,184,.12)" : "rgba(100,116,139,.12)";
  }

  const brlShort = (v) => "R$ " + Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 0 });

  function barOptions(extra) {
    return Object.assign({
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "circle", padding: 14 } },
        tooltip: {
          backgroundColor: isDark() ? "#0b1020" : "#0f172a",
          padding: 10, cornerRadius: 8, displayColors: true,
          callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${money(ctx.parsed.y ?? ctx.parsed)}` },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true } },
        y: {
          beginAtZero: true,
          grid: { color: gridColor(), drawTicks: false },
          border: { display: false },
          ticks: { callback: (v) => brlShort(v), maxTicksLimit: 6 },
        },
      },
    }, extra || {});
  }

  function registerCharts() {
    if (!window.Chart) return;
    chartDefaults();
    Chart.helpers = Chart.helpers || {};
  }

  registerCharts();

  window.FC = {
    PALETTE, money, isDark, chartDefaults, gridColor, barOptions, applyTheme, brlShort,
    pieOptions() {
      return {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "62%",
        plugins: {
          legend: { position: "right", labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, pointStyle: "circle", padding: 12 } },
          tooltip: {
            backgroundColor: isDark() ? "#0b1020" : "#0f172a",
            padding: 10, cornerRadius: 8,
            callbacks: {
              label: (ctx) => {
                const total = ctx.dataset.data.reduce((a, b) => a + b, 0) || 1;
                const pct = ((ctx.parsed / total) * 100).toFixed(1).replace(".", ",");
                return ` ${ctx.label}: ${money(ctx.parsed)} (${pct}%)`;
              },
            },
          },
        },
      };
    },
  };

  // reaplica defaults quando o tema muda (os gráficos são recriados pelas páginas)
  window.addEventListener("fc:theme", () => {
    chartDefaults();
    document.dispatchEvent(new CustomEvent("fc:rebuild-charts"));
  });
})();
