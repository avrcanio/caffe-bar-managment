(function () {
  function applyFlatpickr(root) {
    if (!window.flatpickr) return;

    const dateSelectors = [
      'input[type="date"]',
      'input.vDateField',
      'input.js-flatpickr-date',
    ];
    const datetimeSelectors = [
      'input[type="datetime-local"]',
      'input.vDateTimeField',
      'input.js-flatpickr-datetime',
    ];

    const dateInputs = root.querySelectorAll(dateSelectors.join(","));
    dateInputs.forEach((input) => {
      if (input._flatpickr) return;
      window.flatpickr(input, {
        dateFormat: "d.m.Y",
        allowInput: true,
        locale: "hr",
      });
    });

    const datetimeInputs = root.querySelectorAll(datetimeSelectors.join(","));
    datetimeInputs.forEach((input) => {
      if (input._flatpickr) return;
      window.flatpickr(input, {
        dateFormat: "d.m.Y H:i",
        enableTime: true,
        time_24hr: true,
        allowInput: true,
        locale: "hr",
      });
    });

    // Hide Django's default date/time shortcuts to avoid double UI.
    root.querySelectorAll(".datetimeshortcuts").forEach((el) => {
      el.classList.add("flatpickr-hidden-shortcuts");
    });
  }

  function bindOnFocusInit(root) {
    root.addEventListener("focusin", (event) => {
      const input = event.target;
      if (!input || input._flatpickr) return;
      if (input.matches("input.js-flatpickr-date")) {
        window.flatpickr(input, {
          dateFormat: "d.m.Y",
          allowInput: true,
          locale: "hr",
        });
      }
      if (input.matches("input.js-flatpickr-datetime")) {
        window.flatpickr(input, {
          dateFormat: "d.m.Y H:i",
          enableTime: true,
          time_24hr: true,
          allowInput: true,
          locale: "hr",
        });
      }
    });
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
            "input[name=\"issued_at__gte\"], input[name=\"issued_at__lte\"], input[name=\"invoice__issued_at__gte\"], input[name=\"invoice__issued_at__lte\"]"
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

  document.addEventListener("DOMContentLoaded", () => {
    applyFlatpickr(document);
    bindClearDatetimeButtons(document);
    bindOnFocusInit(document);
  });

  document.addEventListener("formset:added", (event) => {
    if (event && event.target) {
      applyFlatpickr(event.target);
      bindClearDatetimeButtons(event.target);
      bindOnFocusInit(event.target);
    }
  });
})();
