document.addEventListener("DOMContentLoaded", function () {
  var inputs = document.querySelectorAll('input[name$="-price"][data-line-total]');
  inputs.forEach(function (input) {
    if (input.dataset.lineTotalInjected === "1") {
      return;
    }
    input.dataset.lineTotalInjected = "1";
    var text = input.getAttribute("data-line-total");
    if (!text) {
      return;
    }
    var hint = document.createElement("div");
    hint.className = "line-total-hint";
    hint.textContent = text;
    input.insertAdjacentElement("afterend", hint);
  });
});
