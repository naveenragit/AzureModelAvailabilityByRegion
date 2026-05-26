// Azure Model Availability Dashboard - vanilla JS
const $ = (id) => document.getElementById(id);
const state = {
  subs: [],
  locations: [],
  modelsA: [],
  modelsB: [],
  usagesA: [],
  usagesB: [],
  capFilter: new Set(),
  sort: { key: "name", dir: 1 },
};

const CAPS = ["chatCompletion", "completion", "embeddings", "imageGeneration", "audio", "transcription", "fineTune", "responses", "assistants"];

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status} ${path}: ${text.slice(0, 300)}`);
  }
  return r.json();
}

function setStatus(msg, err = false) {
  const el = $("status");
  el.textContent = msg;
  el.classList.toggle("err", !!err);
}

async function init() {
  try {
    setStatus("Loading subscriptions…");
    state.subs = await api("/api/subscriptions");
    const sel = $("subscription");
    sel.innerHTML = state.subs
      .map((s) => `<option value="${s.subscriptionId}">${s.displayName || s.subscriptionId}</option>`)
      .join("");
    if (!state.subs.length) {
      setStatus("No subscriptions found. Run `az login`.", true);
      return;
    }
    await loadLocations();
    renderCapChips();
    setStatus(`Ready. ${state.subs.length} subscription(s).`);
  } catch (e) {
    setStatus(e.message, true);
  }
}

async function loadLocations() {
  const sub = $("subscription").value;
  if (!sub) return;
  setStatus("Loading regions…");
  state.locations = await api(`/api/subscriptions/${sub}/locations`);
  const opts = state.locations
    .filter((l) => !l.name.startsWith("euap") && !l.name.includes("stage"))
    .sort((a, b) => (a.displayName || a.name).localeCompare(b.displayName || b.name))
    .map((l) => `<option value="${l.name}">${l.displayName || l.name} (${l.name})</option>`)
    .join("");
  $("regionA").innerHTML = opts;
  $("regionB").innerHTML = opts;
  // sensible defaults
  const defaults = ["eastus", "swedencentral", "westus3", "northcentralus"];
  for (const d of defaults) {
    if ([...$("regionA").options].some((o) => o.value === d)) {
      $("regionA").value = d;
      break;
    }
  }
  setStatus(`${state.locations.length} regions.`);
}

function renderCapChips() {
  $("caps").innerHTML = CAPS.map(
    (c) => `<span class="chip" data-cap="${c}">${c}</span>`
  ).join("");
  $("caps").querySelectorAll(".chip").forEach((el) => {
    el.addEventListener("click", () => {
      const c = el.dataset.cap;
      if (state.capFilter.has(c)) state.capFilter.delete(c);
      else state.capFilter.add(c);
      el.classList.toggle("active");
      renderTables();
    });
  });
}

async function loadModels() {
  const sub = $("subscription").value;
  const locA = $("regionA").value;
  const locB = $("regionB").value;
  const mode = $("mode").value;
  if (!sub || !locA) return;
  try {
    setStatus(`Loading models for ${locA}${mode === "compare" ? " & " + locB : ""}…`);
    $("titleA").textContent = `Region: ${locA}`;
    if (mode === "compare") {
      $("titleB").textContent = `Region: ${locB}`;
      const [a, b] = await Promise.all([
        api(`/api/subscriptions/${sub}/locations/${locA}/bundle`),
        api(`/api/subscriptions/${sub}/locations/${locB}/bundle`),
      ]);
      state.modelsA = a.models || [];
      state.usagesA = a.usages || [];
      state.modelsB = b.models || [];
      state.usagesB = b.usages || [];
    } else {
      const a = await api(`/api/subscriptions/${sub}/locations/${locA}/bundle`);
      state.modelsA = a.models || [];
      state.usagesA = a.usages || [];
      state.modelsB = [];
      state.usagesB = [];
    }
    setStatus(`Loaded ${state.modelsA.length}${mode === "compare" ? " / " + state.modelsB.length : ""} model(s).`);
    renderTables();
  } catch (e) {
    setStatus(e.message, true);
  }
}

function applyFilters(models) {
  const q = $("search").value.trim().toLowerCase();
  return models.filter((m) => {
    if (q) {
      const hay = `${m.name || ""} ${m.format || ""} ${m.version || ""} ${m.kind || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (state.capFilter.size) {
      const caps = new Set(m.capabilityKeys || []);
      for (const c of state.capFilter) if (!caps.has(c)) return false;
    }
    return true;
  });
}

function sortModels(models) {
  const { key, dir } = state.sort;
  return [...models].sort((a, b) => {
    const av = (a[key] ?? "").toString().toLowerCase();
    const bv = (b[key] ?? "").toString().toLowerCase();
    return av < bv ? -dir : av > bv ? dir : 0;
  });
}

function formatBadge(format) {
  const f = (format || "").toLowerCase();
  return `<span class="badge ${f}">${format || "?"}</span>`;
}

function modelRow(m, usages) {
  const skus = (m.skus || []).map((s) => `${s.name}${s.capacity?.default != null ? `(${s.capacity.default})` : ""}`).join(", ");
  const caps = (m.capabilityKeys || []).slice(0, 5).map((c) => `<span class="badge">${c}</span>`).join("");
  const deprecation = m.deprecation
    ? `${m.deprecation.inference || m.deprecation.fineTune || ""}`
    : "";
  const dep = deprecation ? `<span class="badge deprecated">${deprecation.slice(0, 10)}</span>` : "";
  return `<tr data-name="${m.name}" data-format="${m.format}" data-version="${m.version}">
    <td>${m.name || ""}</td>
    <td>${formatBadge(m.format)}</td>
    <td>${m.version || ""}</td>
    <td>${skus}</td>
    <td>${caps}</td>
    <td>${dep}</td>
    <td>${m.lifecycleStatus || ""}</td>
  </tr>`;
}

function renderTable(tableEl, summaryEl, models, usages) {
  const filtered = sortModels(applyFilters(models));
  const headers = [
    ["name", "Model"],
    ["format", "Publisher"],
    ["version", "Version"],
    ["skus", "SKUs"],
    ["caps", "Capabilities"],
    ["deprecation", "Deprecation"],
    ["lifecycleStatus", "Status"],
  ];
  tableEl.querySelector("thead").innerHTML = "<tr>" +
    headers.map(([k, label]) => {
      const arrow = state.sort.key === k ? (state.sort.dir > 0 ? " ▲" : " ▼") : "";
      return `<th data-key="${k}">${label}${arrow}</th>`;
    }).join("") + "</tr>";
  tableEl.querySelector("tbody").innerHTML = filtered.map((m) => modelRow(m, usages)).join("");
  summaryEl.textContent = `${filtered.length} of ${models.length} models shown`;

  tableEl.querySelectorAll("thead th").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.dataset.key;
      if (!k) return;
      if (state.sort.key === k) state.sort.dir *= -1;
      else { state.sort.key = k; state.sort.dir = 1; }
      renderTables();
    });
  });
  tableEl.querySelectorAll("tbody tr").forEach((tr) => {
    tr.addEventListener("click", () => {
      const m = (models).find((x) => x.name === tr.dataset.name && x.format === tr.dataset.format && x.version === tr.dataset.version);
      if (m) openDrawer(m, usages);
    });
  });
}

function renderTables() {
  const mode = $("mode").value;
  document.querySelector("main").classList.toggle("compare", mode === "compare");
  $("paneB").style.display = mode === "compare" ? "" : "none";
  $("paneDiff").style.display = mode === "compare" ? "" : "none";
  document.querySelector(".region-b-wrap").style.display = mode === "compare" ? "" : "none";

  renderTable($("tableA"), $("summaryA"), state.modelsA, state.usagesA);
  if (mode === "compare") {
    renderTable($("tableB"), $("summaryB"), state.modelsB, state.usagesB);
    renderDiff();
  }
}

function keyOf(m) { return `${m.format}/${m.name}@${m.version}`; }

function renderDiff() {
  const a = new Map(state.modelsA.map((m) => [keyOf(m), m]));
  const b = new Map(state.modelsB.map((m) => [keyOf(m), m]));
  const onlyA = [...a.keys()].filter((k) => !b.has(k)).sort();
  const onlyB = [...b.keys()].filter((k) => !a.has(k)).sort();
  const common = [...a.keys()].filter((k) => b.has(k)).sort();
  $("diff").innerHTML = `
    <div class="col"><h3>Only in A (${onlyA.length})</h3><ul>${onlyA.map((k) => `<li>${k}</li>`).join("")}</ul></div>
    <div class="col"><h3>Common (${common.length})</h3><ul>${common.map((k) => `<li>${k}</li>`).join("")}</ul></div>
    <div class="col"><h3>Only in B (${onlyB.length})</h3><ul>${onlyB.map((k) => `<li>${k}</li>`).join("")}</ul></div>
  `;
}

function openDrawer(m, usages) {
  $("drawerTitle").textContent = `${m.format}/${m.name}@${m.version}`;
  const related = (usages || []).filter((u) => {
    const n = (u.name && (u.name.localizedValue || u.name.value)) || "";
    return n && (m.skus || []).some((s) => (s.usageName || s.name || "").includes(n) || n.includes(s.name || ""));
  });
  const payload = { normalized: m, matchedUsages: related };
  $("drawerBody").textContent = JSON.stringify(payload, null, 2);
  $("drawer").classList.remove("hidden");
}

function exportCsv() {
  const rows = applyFilters(state.modelsA);
  const header = ["region", "name", "format", "version", "lifecycleStatus", "skus", "capabilities", "deprecation"];
  const out = [header.join(",")];
  const locA = $("regionA").value;
  for (const m of rows) {
    out.push([
      locA,
      m.name, m.format, m.version, m.lifecycleStatus || "",
      `"${(m.skus || []).map((s) => s.name).join(";")}"`,
      `"${(m.capabilityKeys || []).join(";")}"`,
      `"${JSON.stringify(m.deprecation || {}).replace(/"/g, "'")}"`,
    ].join(","));
  }
  if ($("mode").value === "compare") {
    const locB = $("regionB").value;
    for (const m of applyFilters(state.modelsB)) {
      out.push([
        locB,
        m.name, m.format, m.version, m.lifecycleStatus || "",
        `"${(m.skus || []).map((s) => s.name).join(";")}"`,
        `"${(m.capabilityKeys || []).join(";")}"`,
        `"${JSON.stringify(m.deprecation || {}).replace(/"/g, "'")}"`,
      ].join(","));
    }
  }
  const blob = new Blob([out.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `models-${Date.now()}.csv`;
  a.click();
}

// Wire-up
$("subscription").addEventListener("change", loadLocations);
$("mode").addEventListener("change", renderTables);
$("load").addEventListener("click", loadModels);
$("search").addEventListener("input", () => renderTables());
$("exportCsv").addEventListener("click", exportCsv);
$("closeDrawer").addEventListener("click", () => $("drawer").classList.add("hidden"));

init();
