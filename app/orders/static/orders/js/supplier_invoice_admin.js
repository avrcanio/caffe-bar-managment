(function () {
  function normalizeDecimalComma(value) {
    if (value == null) return '';
    var v = String(value);
    // Treat '.' as decimal separator too, then keep only digits and one comma.
    v = v.replace(/\./g, ',');
    // Remove spaces and any non-digit/non-comma chars.
    v = v.replace(/[^0-9,]/g, '');
    var parts = v.split(',');
    if (parts.length <= 1) return parts[0];
    return parts[0] + ',' + parts.slice(1).join('').slice(0, 2);
  }

  function setDisabled(row, disabled) {
    if (!row) return;
    row.style.display = '';
    row.querySelectorAll('input, select, textarea, button').forEach(function (el) {
      el.disabled = disabled;
    });
  }

  function clearRow(row) {
    if (!row) return;
    row.querySelectorAll('input, select, textarea').forEach(function (el) {
      if (el.tagName === 'SELECT') {
        el.selectedIndex = 0;
      } else {
        el.value = '';
      }
    });
  }

  function ensureModeBadge(isAddForm) {
    if (document.querySelector('#supplier-invoice-mode-badge')) return;
    var h1 = document.querySelector('#content h1');
    if (!h1) return;
    var badge = document.createElement('span');
    badge.id = 'supplier-invoice-mode-badge';
    badge.textContent = isAddForm ? 'ADD' : 'EDIT';
    badge.style.marginLeft = '8px';
    badge.style.padding = '2px 6px';
    badge.style.borderRadius = '10px';
    badge.style.fontSize = '11px';
    badge.style.fontWeight = '700';
    badge.style.letterSpacing = '0.5px';
    badge.style.background = isAddForm ? '#1f6feb' : '#6e7781';
    badge.style.color = '#fff';
    badge.style.boxShadow = '0 1px 2px rgba(0,0,0,0.2)';
    h1.appendChild(badge);
  }

  function applyTermStyles(term, depositActive) {
    var cashRow = document.querySelector('.form-row.field-cash_account');
    var apRow = document.querySelector('.form-row.field-ap_account');
    var depositRow = document.querySelector('.form-row.field-deposit_account');
    [cashRow, apRow, depositRow].forEach(function (row) {
      if (row) row.classList.remove('term-cash', 'term-deferred', 'term-neutral');
    });
    if (term === 'cash') {
      if (cashRow) cashRow.classList.add('term-cash');
      if (apRow) apRow.classList.add('term-cash');
      if (depositRow) depositRow.classList.add(depositActive ? 'term-cash' : 'term-neutral');
    } else if (term === 'deferred') {
      if (cashRow) cashRow.classList.add('term-deferred');
      if (apRow) apRow.classList.add('term-deferred');
      if (depositRow) depositRow.classList.add(depositActive ? 'term-deferred' : 'term-neutral');
    } else {
      if (cashRow) cashRow.classList.add('term-neutral');
      if (apRow) apRow.classList.add('term-neutral');
      if (depositRow) depositRow.classList.add('term-neutral');
    }
  }

  function toggleFields() {
    var terms = document.querySelector('#id_payment_terms');
    var depositTotal = document.querySelector('#id_deposit_total');
    var isAddForm = !document.querySelector('#id_id');
    if (!terms) return;

    ensureModeBadge(isAddForm);

    var cashRow = document.querySelector('.form-row.field-cash_account');
    var apRow = document.querySelector('.form-row.field-ap_account');
    var depositRow = document.querySelector('.form-row.field-deposit_account');

    var depositActive = false;
    if (depositRow && depositTotal) {
      var val = parseFloat((depositTotal.value || '0').replace(',', '.'));
      depositActive = val > 0;
    }

    applyTermStyles(terms.value, depositActive);

    if (terms.value === 'cash') {
      setDisabled(cashRow, false);
      if (apRow) {
        apRow.style.display = 'none';
        setDisabled(apRow, true);
        if (isAddForm) clearRow(apRow);
      }
    } else if (terms.value === 'deferred') {
      setDisabled(apRow, false);
      if (cashRow) {
        cashRow.style.display = 'none';
        setDisabled(cashRow, true);
        if (isAddForm) clearRow(cashRow);
      }
    } else {
      setDisabled(cashRow, false);
      setDisabled(apRow, false);
    }

    if (depositRow && depositTotal) {
      if (depositActive) {
        setDisabled(depositRow, false);
        depositRow.style.display = '';
      } else {
        setDisabled(depositRow, true);
        depositRow.style.display = 'none';
        if (isAddForm) clearRow(depositRow);
      }
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    toggleFields();
    var terms = document.querySelector('#id_payment_terms');
    var depositTotal = document.querySelector('#id_deposit_total');
    if (terms) terms.addEventListener('change', toggleFields);
    if (depositTotal) depositTotal.addEventListener('input', toggleFields);

    // Money inputs: allow numeric keypad input and prefer comma as decimal separator.
    document.querySelectorAll('input.js-decimal-comma').forEach(function (input) {
      input.addEventListener('input', function () {
        var next = normalizeDecimalComma(input.value);
        if (input.value !== next) input.value = next;
      });
      input.addEventListener('blur', function () {
        // Ensure at most 2 decimal digits on blur.
        input.value = normalizeDecimalComma(input.value);
      });
    });
  });
})();
