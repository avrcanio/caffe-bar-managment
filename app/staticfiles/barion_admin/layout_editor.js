(function () {
  "use strict";

  const root = document.getElementById("barion-layout-editor");
  if (!root) return;
  const CANVAS_WIDTH = 1000;
  const CANVAS_HEIGHT = 2000;

  const canvas = document.getElementById("ble-canvas");
  const statusEl = document.getElementById("ble-status");
  const tabsEl = document.getElementById("ble-zone-tabs");
  const addSelectEl = document.getElementById("ble-add-table");
  const addBtnEl = document.getElementById("ble-add-table-btn");
  const saveBtnEl = document.getElementById("ble-save-btn");
  const snapToggleEl = document.getElementById("ble-snap-toggle");
  const zoneFieldEl = document.getElementById("ble-field-zone");
  const selectedLabelEl = document.getElementById("ble-selected-label");
  const applyFieldsBtnEl = document.getElementById("ble-apply-fields-btn");

  const fieldX = document.getElementById("ble-field-x");
  const fieldY = document.getElementById("ble-field-y");
  const fieldW = document.getElementById("ble-field-w");
  const fieldH = document.getElementById("ble-field-h");
  const fieldRotation = document.getElementById("ble-field-rotation");
  const fieldEnabled = document.getElementById("ble-field-enabled");

  const state = {
    layout: null,
    zones: [],
    placements: [],
    availableTables: [],
    selectedZoneId: null,
    selectedPlacementId: null,
    drag: null,
  };

  function setStatus(text, isError) {
    statusEl.textContent = text;
    statusEl.style.color = isError ? "#b00020" : "#1f1f1f";
    statusEl.style.borderColor = isError ? "#f4b4be" : "#d9d9d9";
    statusEl.style.background = isError ? "#fff0f3" : "#f8f8f8";
  }

  function parseNumber(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function clamp(n, min, max) {
    return Math.min(Math.max(n, min), max);
  }

  function maybeSnap(n) {
    if (!snapToggleEl.checked) return n;
    return Math.round(n / 10) * 10;
  }

  function getCookie(name) {
    const cookie = document.cookie
      .split(";")
      .map((v) => v.trim())
      .find((v) => v.startsWith(name + "="));
    if (!cookie) return "";
    return decodeURIComponent(cookie.slice(name.length + 1));
  }

  function defaultSize(shape) {
    if (shape === "rectangle") return { w: 120, h: 80 };
    if (shape === "round") return { w: 90, h: 90 };
    if (shape === "square") return { w: 90, h: 90 };
    return { w: 100, h: 100 };
  }

  function nextTempId() {
    return "new_" + Date.now() + "_" + Math.floor(Math.random() * 10000);
  }

  function selectedPlacement() {
    return state.placements.find((p) => String(p.layout_table_id) === String(state.selectedPlacementId)) || null;
  }

  function renderZoneTabs() {
    tabsEl.innerHTML = "";
    state.zones.forEach((zone) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "ble-zone-tab" + (zone.id === state.selectedZoneId ? " is-active" : "");
      b.textContent = zone.name;
      b.addEventListener("click", () => {
        state.selectedZoneId = zone.id;
        state.selectedPlacementId = null;
        renderAll();
      });
      tabsEl.appendChild(b);
    });
  }

  function renderZoneField() {
    zoneFieldEl.innerHTML = "";
    state.zones.forEach((zone) => {
      const o = document.createElement("option");
      o.value = String(zone.id);
      o.textContent = zone.name;
      zoneFieldEl.appendChild(o);
    });
  }

  function renderAddSelect() {
    addSelectEl.innerHTML = "";
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Select table...";
    addSelectEl.appendChild(placeholder);

    state.availableTables.forEach((t) => {
      const o = document.createElement("option");
      o.value = String(t.id);
      o.textContent = t.label + " (" + t.shape + ")";
      addSelectEl.appendChild(o);
    });
  }

  function renderFields() {
    const p = selectedPlacement();
    if (!p) {
      selectedLabelEl.textContent = "None";
      [fieldX, fieldY, fieldW, fieldH, fieldRotation].forEach((el) => (el.value = ""));
      fieldEnabled.checked = true;
      zoneFieldEl.value = String(state.selectedZoneId || "");
      return;
    }

    selectedLabelEl.textContent = p.label + " [#" + p.table_id + "]";
    fieldX.value = String(p.x);
    fieldY.value = String(p.y);
    fieldW.value = String(p.w);
    fieldH.value = String(p.h);
    fieldRotation.value = String(p.rotation || 0);
    fieldEnabled.checked = !!p.is_enabled;
    zoneFieldEl.value = String(p.zone_id);
  }

  function placementStyle(p) {
    return {
      left: p.x + "px",
      top: p.y + "px",
      width: p.w + "px",
      height: p.h + "px",
      transform: "rotate(" + (p.rotation || 0) + "deg)",
      zIndex: String(p.z_index || 0),
    };
  }

  function beginDrag(e, placementId, mode) {
    const p = state.placements.find((row) => String(row.layout_table_id) === String(placementId));
    if (!p) return;

    state.selectedPlacementId = placementId;
    const rect = canvas.getBoundingClientRect();
    state.drag = {
      placementId,
      mode,
      startX: e.clientX,
      startY: e.clientY,
      x: p.x,
      y: p.y,
      w: p.w,
      h: p.h,
      canvasRect: rect,
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", endDrag);
    e.preventDefault();
    renderAll();
  }

  function onMouseMove(e) {
    if (!state.drag) return;
    const p = state.placements.find((row) => String(row.layout_table_id) === String(state.drag.placementId));
    if (!p) return;

    const dx = e.clientX - state.drag.startX;
    const dy = e.clientY - state.drag.startY;

    if (state.drag.mode === "drag") {
      let x = maybeSnap(state.drag.x + dx);
      let y = maybeSnap(state.drag.y + dy);
      x = clamp(x, 0, CANVAS_WIDTH - p.w);
      y = clamp(y, 0, CANVAS_HEIGHT - p.h);
      p.x = x;
      p.y = y;
    } else {
      let w = maybeSnap(state.drag.w + dx);
      let h = maybeSnap(state.drag.h + dy);
      w = clamp(w, 1, CANVAS_WIDTH - p.x);
      h = clamp(h, 1, CANVAS_HEIGHT - p.y);
      p.w = w;
      p.h = h;
    }
    renderAll();
  }

  function endDrag() {
    state.drag = null;
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseup", endDrag);
    renderFields();
  }

  function renderCanvas() {
    canvas.innerHTML = "";
    const visible = state.placements.filter((p) => p.zone_id === state.selectedZoneId);
    visible.forEach((p) => {
      const el = document.createElement("div");
      el.className = "ble-table";
      if (!p.is_enabled) el.classList.add("is-disabled");
      if (String(p.layout_table_id) === String(state.selectedPlacementId)) el.classList.add("is-selected");

      const style = placementStyle(p);
      Object.assign(el.style, style);
      el.dataset.placementId = String(p.layout_table_id);

      const label = document.createElement("div");
      label.className = "ble-table-label";
      label.textContent = p.label + (p.is_vip ? " VIP" : "");
      el.appendChild(label);

      const handle = document.createElement("div");
      handle.className = "ble-table-handle";
      handle.addEventListener("mousedown", (ev) => beginDrag(ev, p.layout_table_id, "resize"));
      el.appendChild(handle);

      el.addEventListener("mousedown", (ev) => {
        if (ev.target === handle) return;
        beginDrag(ev, p.layout_table_id, "drag");
      });
      el.addEventListener("click", () => {
        state.selectedPlacementId = p.layout_table_id;
        renderAll();
      });
      canvas.appendChild(el);
    });
  }

  function renderAll() {
    renderZoneTabs();
    renderZoneField();
    renderAddSelect();
    renderCanvas();
    renderFields();
  }

  function validatePlacement(p) {
    p.x = clamp(parseNumber(p.x, 0), 0, CANVAS_WIDTH);
    p.y = clamp(parseNumber(p.y, 0), 0, CANVAS_HEIGHT);
    p.w = clamp(parseNumber(p.w, 90), 1, CANVAS_WIDTH - p.x);
    p.h = clamp(parseNumber(p.h, 90), 1, CANVAS_HEIGHT - p.y);
    p.rotation = clamp(parseNumber(p.rotation, 0), -360, 360);
    p.z_index = parseNumber(p.z_index, 0);
    p.zone_id = parseNumber(p.zone_id, state.selectedZoneId || 0);
    p.is_enabled = !!p.is_enabled;
  }

  function applySidebarFields() {
    const p = selectedPlacement();
    if (!p) {
      setStatus("Select a table first.", true);
      return;
    }

    const nextX = clamp(parseNumber(fieldX.value, p.x), 0, CANVAS_WIDTH);
    const nextY = clamp(parseNumber(fieldY.value, p.y), 0, CANVAS_HEIGHT);
    const nextW = clamp(parseNumber(fieldW.value, p.w), 1, CANVAS_WIDTH - nextX);
    const nextH = clamp(parseNumber(fieldH.value, p.h), 1, CANVAS_HEIGHT - nextY);
    const nextRotation = clamp(parseNumber(fieldRotation.value, p.rotation || 0), -360, 360);

    const requestedZoneId = parseNumber(zoneFieldEl.value, p.zone_id);
    const zoneExists = state.zones.some((z) => z.id === requestedZoneId);
    const nextZoneId = zoneExists ? requestedZoneId : p.zone_id;

    p.x = nextX;
    p.y = nextY;
    p.w = nextW;
    p.h = nextH;
    p.rotation = nextRotation;
    p.zone_id = nextZoneId;
    p.is_enabled = !!fieldEnabled.checked;

    // Keep moved table visible/selected even when zone is changed via sidebar.
    state.selectedZoneId = p.zone_id;
    state.selectedPlacementId = p.layout_table_id;
    setStatus("Applied to selected table. Click Save to persist.");
    renderAll();
  }

  async function fetchData() {
    setStatus("Loading layout data...");
    const r = await fetch(root.dataset.dataUrl, { credentials: "same-origin" });
    if (!r.ok) throw new Error("Failed to load editor data.");
    const data = await r.json();
    state.layout = data.layout;
    state.zones = (data.zones || []).slice().sort((a, b) => (a.order - b.order) || (a.id - b.id));
    state.placements = (data.placements || []).map((p) => ({ ...p }));
    state.availableTables = (data.available_tables || []).map((t) => ({ ...t }));
    state.selectedZoneId = state.zones.length ? state.zones[0].id : null;
    state.selectedPlacementId = null;
    renderAll();
    setStatus("Loaded. Drag tables, resize corner, then save.");
  }

  async function saveData() {
    setStatus("Saving...");
    state.placements.forEach(validatePlacement);
    const payload = {
      placements: state.placements.map((p) => ({
        layout_table_id: String(p.layout_table_id).startsWith("new_") ? null : p.layout_table_id,
        table_id: p.table_id,
        x: p.x,
        y: p.y,
        w: p.w,
        h: p.h,
        rotation: p.rotation || 0,
        is_enabled: !!p.is_enabled,
        zone_id: p.zone_id,
        z_index: p.z_index || 0,
      })),
    };

    const r = await fetch(root.dataset.saveUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCookie("csrftoken"),
      },
      body: JSON.stringify(payload),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      setStatus(data.detail || "Save failed.", true);
      return;
    }
    setStatus("Saved. updated=" + data.updated + " created=" + data.created);
    await fetchData();
  }

  function addSelectedTable() {
    const tableId = parseNumber(addSelectEl.value, 0);
    if (!tableId || !state.selectedZoneId) return;
    const table = state.availableTables.find((t) => t.id === tableId);
    if (!table) return;

    const size = defaultSize(table.shape);
    const zoneCount = state.placements.filter((p) => p.zone_id === state.selectedZoneId).length;
    const offset = (zoneCount * 24) % 1700;
    const placement = {
      layout_table_id: nextTempId(),
      table_id: table.id,
      label: table.label,
      shape: table.shape,
      capacity: table.capacity,
      is_vip: table.is_vip,
      x: 20 + offset,
      y: 20 + offset,
      w: size.w,
      h: size.h,
      rotation: 0,
      is_enabled: true,
      z_index: state.placements.length + 1,
      zone_id: state.selectedZoneId,
    };
    state.placements.push(placement);
    state.availableTables = state.availableTables.filter((t) => t.id !== table.id);
    state.selectedPlacementId = placement.layout_table_id;
    renderAll();
  }

  addBtnEl.addEventListener("click", addSelectedTable);
  saveBtnEl.addEventListener("click", () => {
    saveData().catch((err) => setStatus(err.message || "Save error", true));
  });
  applyFieldsBtnEl.addEventListener("click", applySidebarFields);

  fetchData().catch((err) => setStatus(err.message || "Load error", true));
})();
