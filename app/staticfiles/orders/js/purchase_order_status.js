document.addEventListener("DOMContentLoaded", function () {
  var statusField = document.getElementById("id_status");
  if (!statusField) {
    highlightListRows();
    return;
  }

  function toggleStatusClass() {
    var isReceived = statusField.value === "received";
    statusField.classList.toggle("status-received", isReceived);
  }

  toggleStatusClass();
  statusField.addEventListener("change", toggleStatusClass);

  highlightListRows();
});

function highlightListRows() {
  var rows = document.querySelectorAll("tr.model-purchaseorder");
  rows.forEach(function (row) {
    var cell = row.querySelector("td.field-status");
    if (!cell) {
      return;
    }
    var value = cell.textContent.trim().toLowerCase();
    if (value === "primljena" || value === "received") {
      row.classList.add("status-received-row");
    }
  });
}
