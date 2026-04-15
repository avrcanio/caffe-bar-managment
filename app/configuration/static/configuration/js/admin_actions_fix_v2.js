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

  function copyTextToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }

    return new Promise((resolve, reject) => {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.top = "-1000px";
      textarea.style.left = "-1000px";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();

      try {
        const copied = document.execCommand("copy");
        document.body.removeChild(textarea);
        if (!copied) {
          reject(new Error("Copy command failed"));
          return;
        }
        resolve();
      } catch (error) {
        document.body.removeChild(textarea);
        reject(error);
      }
    });
  }

  function setCopyFeedback(feedback, text, isError) {
    feedback.textContent = text;
    feedback.style.marginLeft = "8px";
    feedback.style.fontSize = "12px";
    feedback.style.color = isError ? "#8a1f11" : "#1f5131";

    if (feedback._hideTimer) {
      window.clearTimeout(feedback._hideTimer);
    }
    feedback._hideTimer = window.setTimeout(() => {
      feedback.textContent = "";
    }, 2200);
  }

  function enhanceInventoryPublicLinkMessages(root) {
    root.querySelectorAll("[data-copy-public-link]").forEach((trigger) => {
      if (trigger.dataset.copyBound === "1") return;
      trigger.dataset.copyBound = "1";

      const url = trigger.dataset.copyPublicLink;
      if (!url) return;

      if (trigger.classList.contains("inventory-public-link-anchor")) {
        trigger.style.fontWeight = "600";
      }
      if (trigger.classList.contains("inventory-public-link-copy")) {
        trigger.style.marginLeft = "8px";
        trigger.style.display = "inline-flex";
        trigger.style.alignItems = "center";
        trigger.style.justifyContent = "center";
        trigger.style.width = "24px";
        trigger.style.height = "24px";
        trigger.style.padding = "0";
        trigger.style.border = "1px solid rgba(31, 81, 49, 0.25)";
        trigger.style.borderRadius = "6px";
        trigger.style.background = "#fff";
        trigger.style.color = "#1f5131";
        trigger.style.cursor = "pointer";
        trigger.style.verticalAlign = "middle";
      }

      const message = trigger.closest("li, div");
      const feedback = message ? message.querySelector(".inventory-public-link-feedback") : null;

      trigger.addEventListener("click", async (event) => {
        event.preventDefault();
        try {
          await copyTextToClipboard(url);
          if (feedback) {
            setCopyFeedback(feedback, "Kopirano u clipboard", false);
          }
        } catch (_error) {
          if (feedback) {
            setCopyFeedback(feedback, "Kopiranje nije uspjelo", true);
          }
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensureAdminActionHooks();
    bindClearDatetimeButtons(document);
    moveSalesPriceItemEmptyForm(document);
    enhanceInventoryPublicLinkMessages(document);
  });
  document.addEventListener("click", enableShiftRangeRowClick);
})();
