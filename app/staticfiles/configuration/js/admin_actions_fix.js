(function () {
  function ensureAdminActionHooks() {
    document.querySelectorAll("#changelist-form").forEach((form) => {
      if (!form.classList.contains("result-list-wrapper")) {
        form.classList.add("result-list-wrapper");
      }
      const toggle = form.querySelector("#action-toggle");
      if (toggle && !toggle.classList.contains("action-toggle")) {
        toggle.classList.add("action-toggle");
      }
      const headerToggle = form.querySelector('thead input[type="checkbox"]');
      if (headerToggle && !headerToggle.classList.contains("action-toggle")) {
        headerToggle.classList.add("action-toggle");
      }
      const resultList = form.querySelector(".result-list");
      if (!resultList) {
        const results = form.querySelector("#result_list");
        if (results) {
          results.classList.add("result-list");
        }
      }
    });
  }

  function enableShiftRangeRowClick(event) {
    if (!event.shiftKey) return;
    const target = event.target;
    if (target.closest("a, button, input, select, textarea, label")) return;
    const row = target.closest("tr");
    if (!row) return;
    const checkbox = row.querySelector("input.action-select");
    if (!checkbox) return;
    checkbox.click();
  }

  function bindClearDatetimeButtons(root) {
    root.querySelectorAll(".js-clear-datetime").forEach((btn) => {
      if (btn.dataset.bound === "1") return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", () => {
        const form = btn.closest("form");
        if (!form) return;
        form
          .querySelectorAll(
            'input[name="issued_at__gte"], input[name="issued_at__lte"], input[name="invoice__issued_at__gte"], input[name="invoice__issued_at__lte"]'
          )
          .forEach((input) => {
            input.value = "";
            if (input._flatpickr) {
              input._flatpickr.clear();
            }
          });
        form.submit();
      });
    });
  }

  function moveSalesPriceItemEmptyForm(root) {
    const group = root.querySelector("#salespriceitem_set-group");
    if (!group) return;
    const table = group.querySelector("table");
    const emptyRow = group.querySelector("tr.empty-form");
    const firstRow = group.querySelector("tbody tr.inline-related:not(.empty-form)");
    if (table && emptyRow && firstRow) {
      emptyRow.parentNode.insertBefore(emptyRow, firstRow);
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensureAdminActionHooks();
    bindClearDatetimeButtons(document);
    moveSalesPriceItemEmptyForm(document);
  });
  document.addEventListener("click", enableShiftRangeRowClick);
})();
