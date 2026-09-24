// NBA Fan Board dashboard behaviour. Loaded with `defer` from templates/index.html, so the
// DOM is fully parsed by the time this runs (FE-04: moved out of an inline <script> so a
// strict `script-src 'self'` CSP can be used).
(function () {
  "use strict";

  const dashboardState = JSON.parse(document.getElementById("dashboard-state").textContent);

  function prettyNum(v, digits = 1) {
    if (v === null || v === undefined || v === "") return "n/a";
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(digits) : "n/a";
  }

  function prettyPct(v) {
    if (v === null || v === undefined || v === "") return "n/a";
    const n = Number(v);
    return Number.isFinite(n) ? `${(n * 100).toFixed(1)}%` : "n/a";
  }

  function applyGameFilters() {
    const q = document.getElementById("search-games").value.trim().toLowerCase();
    const activeChip = document.querySelector(".chip.is-active")?.dataset.chip || "all";
    const items = Array.from(document.querySelectorAll(".game-item"));

    let visibleCount = 0;
    items.forEach((item) => {
      const searchText = item.dataset.search || "";
      const type = item.dataset.filterType;
      const confidence = item.dataset.confidence;

      const searchMatch = !q || searchText.includes(q);
      let chipMatch = true;
      if (activeChip === "bet") chipMatch = type === "bet";
      else if (activeChip === "no_edge") chipMatch = type === "no_edge";
      else if (activeChip === "high") chipMatch = confidence === "high";

      const show = searchMatch && chipMatch;
      item.classList.toggle("hidden", !show);
      if (show) visibleCount += 1;
    });

    document.getElementById("empty-filter-msg").classList.toggle("hidden", visibleCount > 0);
  }

  function initFilters() {
    const input = document.getElementById("search-games");
    input.addEventListener("input", applyGameFilters);

    // Event delegation: the chip buttons don't change, but this also tolerates a future
    // re-render of the chip row without needing to rebind.
    document.getElementById("filter-chips").addEventListener("click", (e) => {
      const chip = e.target.closest(".chip");
      if (!chip) return;
      document.querySelectorAll(".chip").forEach((c) => c.classList.remove("is-active"));
      chip.classList.add("is-active");
      applyGameFilters();
    });
  }

  function initFilterForm() {
    // Was onchange="this.form.submit()" inline on each <select> (FE-04).
    const seasonSelect = document.getElementById("season");
    const dateSelect = document.getElementById("game_date");
    seasonSelect.addEventListener("change", () => seasonSelect.form.submit());
    dateSelect.addEventListener("change", () => dateSelect.form.submit());
  }

  const modal = document.getElementById("summary-modal");
  const closeModalBtn = modal.querySelector(".close-modal");
  const modalCard = modal.querySelector(".modal-card");
  // FE-F20: fallback focus target (programmatically focusable, but not tab-reachable itself
  // since getFocusableElements() excludes tabindex="-1") for when the modal has no other
  // focusable descendant to pull focus back into.
  modalCard.tabIndex = -1;
  let lastFocusedElement = null;

  function getFocusableElements(container) {
    return Array.from(
      container.querySelectorAll(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
      )
    );
  }

  function openSummary(btn) {
    const game = JSON.parse(btn.dataset.game);
    const d = game.details || {};

    document.getElementById("modal-title").textContent = `Game Summary: ${game.matchup}`;
    document.getElementById("modal-matchup").textContent = `Game Date: ${dashboardState.game_date}`;
    document.getElementById("m-pick").textContent = game.predicted_winner || "n/a";
    document.getElementById("m-exp-prob").textContent = prettyPct(game.expected_win_prob);
    document.getElementById("m-impl-prob").textContent = prettyPct(game.implied_prob);
    const edgeText = game.edge === null || game.edge === undefined ? "n/a" : `${(game.edge * 100).toFixed(2)}%`;
    document.getElementById("m-edge").textContent = edgeText;
    document.getElementById("m-home-elo").textContent = prettyNum(d.home_elo, 0);
    document.getElementById("m-away-elo").textContent = prettyNum(d.away_elo, 0);

    document.getElementById("m-home-team").textContent = game.home_team || "Home";
    document.getElementById("m-away-team").textContent = game.away_team || "Away";
    document.getElementById("m-home-pts").textContent = prettyNum(d.home_roll_pts);
    document.getElementById("m-home-fg").textContent = prettyNum(d.home_roll_fg_pct, 3);
    document.getElementById("m-home-reb").textContent = prettyNum(d.home_roll_reb);
    document.getElementById("m-home-ast").textContent = prettyNum(d.home_roll_ast);
    document.getElementById("m-home-tov").textContent = prettyNum(d.home_roll_tov);
    document.getElementById("m-home-stocks").textContent = prettyNum(d.home_roll_stocks);
    document.getElementById("m-away-pts").textContent = prettyNum(d.away_roll_pts);
    document.getElementById("m-away-fg").textContent = prettyNum(d.away_roll_fg_pct, 3);
    document.getElementById("m-away-reb").textContent = prettyNum(d.away_roll_reb);
    document.getElementById("m-away-ast").textContent = prettyNum(d.away_roll_ast);
    document.getElementById("m-away-tov").textContent = prettyNum(d.away_roll_tov);
    document.getElementById("m-away-stocks").textContent = prettyNum(d.away_roll_stocks);

    // FE-F4: remember what had focus, move focus into the modal, keep it there.
    lastFocusedElement = document.activeElement;
    modal.classList.remove("hidden");
    closeModalBtn.focus();
  }

  function closeSummary() {
    modal.classList.add("hidden");
    if (lastFocusedElement && typeof lastFocusedElement.focus === "function") {
      lastFocusedElement.focus();
    }
    lastFocusedElement = null;
  }

  function initModal() {
    // Event delegation: the game buttons are rendered server-side in a loop (dynamic rows),
    // so bind once on their container instead of once per button (was onclick="openSummary(this)").
    document.getElementById("game-list").addEventListener("click", (e) => {
      const btn = e.target.closest(".game-button");
      if (!btn) return;
      openSummary(btn);
    });

    // Was onclick="closeSummary()" inline on the button (FE-04).
    closeModalBtn.addEventListener("click", closeSummary);

    modal.addEventListener("click", (e) => {
      if (e.target.id === "summary-modal") closeSummary();
    });

    // FE-F4: Esc closes the modal; Tab/Shift+Tab stay trapped inside it while it's open.
    // FE-F20: bound to `document` (once, here at init -- not re-added per open) instead of
    // `modal`, so it keeps firing even once focus (and therefore the keydown event's target)
    // has moved outside the modal's DOM subtree, e.g. to <body> after a click on
    // non-focusable modal-card content. The `hidden` check below guards it to only act while
    // the modal is actually open.
    document.addEventListener("keydown", (e) => {
      if (modal.classList.contains("hidden")) return;

      if (e.key === "Escape") {
        closeSummary();
        return;
      }

      if (e.key === "Tab") {
        const focusable = getFocusableElements(modal);
        if (focusable.length === 0) {
          // No focusable descendant to trap into -- fall back to the modal card itself.
          e.preventDefault();
          modalCard.focus();
          return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (!modal.contains(document.activeElement)) {
          // Focus escaped the modal subtree entirely (e.g. a click on non-focusable modal
          // content blurred to <body>): pull it back in instead of letting native Tab order
          // continue into the page behind the overlay.
          e.preventDefault();
          (e.shiftKey ? last : first).focus();
          return;
        }

        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    });
  }

  function drawConfidenceBars() {
    const el = document.getElementById("confidence-bars");
    const counts = dashboardState.confidence_distribution || { high: 0, medium: 0, low: 0, unknown: 0 };
    const keys = ["high", "medium", "low", "unknown"];
    const max = Math.max(...keys.map((k) => counts[k] || 0), 1);
    el.textContent = "";
    keys.forEach((k) => {
      const v = counts[k] || 0;
      const pct = (v / max) * 100;

      const row = document.createElement("div");
      row.className = "confidence-row";

      const label = document.createElement("span");
      label.textContent = k.toUpperCase();

      const shell = document.createElement("div");
      shell.className = "bar-shell";
      const fill = document.createElement("div");
      fill.className = `bar-fill ${k}`;
      fill.style.width = `${pct}%`; // CSSOM property assignment, not an HTML string sink.
      shell.appendChild(fill);

      const count = document.createElement("strong");
      count.textContent = String(v);

      row.appendChild(label);
      row.appendChild(shell);
      row.appendChild(count);
      el.appendChild(row);
    });
  }

  const SVG_NS = "http://www.w3.org/2000/svg";

  function svgEl(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.keys(attrs || {}).forEach((key) => node.setAttribute(key, attrs[key]));
    return node;
  }

  function drawTrendChart(points, showBankroll, showCumPl) {
    const svg = document.getElementById("bankroll-chart");
    svg.textContent = "";

    if (!points || points.length === 0) {
      const text = svgEl("text", {
        x: "50%", y: "50%", "text-anchor": "middle", fill: "#946546", "font-size": "16",
      });
      text.textContent = "No season bankroll data yet";
      svg.appendChild(text);
      return;
    }

    const width = 560;
    const height = 340;
    const padL = 46;
    const padR = 16;
    const padT = 18;
    const padB = 38;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    function sx(i) {
      if (points.length === 1) return padL + plotW / 2;
      return padL + (i / (points.length - 1)) * plotW;
    }

    const series = [];
    if (showBankroll) series.push({ key: "balance", color: "#d8752d", label: "Bankroll" });
    if (showCumPl) series.push({ key: "cum_pl", color: "#7f69d8", label: "Cumulative P/L" });
    if (series.length === 0) return;

    const allValues = [];
    series.forEach((s) => points.forEach((p) => allValues.push(Number(p[s.key]))));
    const minY = Math.min(...allValues);
    const maxY = Math.max(...allValues);
    const spanY = Math.max(maxY - minY, 1);

    function sy(v) {
      return padT + ((maxY - v) / spanY) * plotH;
    }

    for (let i = 0; i < 5; i++) {
      const y = padT + (i / 4) * plotH;
      const val = maxY - (i / 4) * spanY;

      svg.appendChild(svgEl("line", {
        x1: padL, y1: y, x2: width - padR, y2: y,
        stroke: "rgba(135,90,60,0.23)", "stroke-width": "1",
      }));

      const label = svgEl("text", {
        x: padL - 8, y: y + 4, "text-anchor": "end", fill: "#946546", "font-size": "11",
      });
      label.textContent = val.toFixed(0);
      svg.appendChild(label);
    }

    svg.appendChild(svgEl("line", {
      x1: padL, y1: height - padB, x2: width - padR, y2: height - padB,
      stroke: "#9a6d45", "stroke-width": "2",
    }));
    svg.appendChild(svgEl("line", {
      x1: padL, y1: padT, x2: padL, y2: height - padB,
      stroke: "#9a6d45", "stroke-width": "2",
    }));

    series.forEach((s) => {
      const d = points.map((p, i) => `${i === 0 ? "M" : "L"} ${sx(i)} ${sy(Number(p[s.key]))}`).join(" ");
      svg.appendChild(svgEl("path", {
        d: d, fill: "none", stroke: s.color, "stroke-width": "3.6",
        "stroke-linecap": "round", "stroke-linejoin": "round",
      }));
    });

    const first = points[0];
    const last = points[points.length - 1];
    [first, last].forEach((pt) => {
      const idx = points.indexOf(pt);
      if (!showBankroll) return;

      // FE-F1: built with createElementNS + textContent instead of an HTML-string sink, so
      // pt.date (a DB-sourced value) can never be parsed as markup.
      const circle = svgEl("circle", {
        cx: sx(idx), cy: sy(Number(pt.balance)), r: "4",
        fill: "#fff4e4", stroke: "#a8632f", "stroke-width": "1.5",
      });
      // FE-F2: guard pt.balance with Number.isFinite before formatting it.
      const balance = Number(pt.balance);
      const balanceText = Number.isFinite(balance) ? balance.toFixed(2) : "n/a";
      const title = document.createElementNS(SVG_NS, "title");
      title.textContent = `${pt.date} bankroll: ${balanceText}`;
      circle.appendChild(title);
      svg.appendChild(circle);
    });
  }

  function redrawChartFromToggles() {
    drawTrendChart(
      dashboardState.bankroll_series || [],
      document.getElementById("show-bankroll").checked,
      document.getElementById("show-cumpl").checked
    );
  }

  initFilterForm();
  initFilters();
  initModal();

  document.getElementById("show-bankroll").addEventListener("change", redrawChartFromToggles);
  document.getElementById("show-cumpl").addEventListener("change", redrawChartFromToggles);

  drawConfidenceBars();
  redrawChartFromToggles();
  applyGameFilters();
})();
