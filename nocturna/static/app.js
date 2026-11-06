const $ = (s, root = document) => root.querySelector(s);
let filter = "";
let selected = null;
let templates = [];
let checklistItems = {};

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, d = 1) => (v === null || v === undefined ? "–" : Number(v).toFixed(d));
const actor = () => $("#actor").value.trim();

try { $("#actor").value = localStorage.getItem("nocturna.actor") || ""; } catch {}
$("#actor").addEventListener("change", () => { try { localStorage.setItem("nocturna.actor", actor()); } catch {} });

async function api(path, opts = {}) {
  const headers = opts.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  const res = await fetch(path, { headers, ...opts });
  const body = res.status === 204 ? null : await res.json();
  if (!res.ok) {
    const d = body?.detail;
    throw new Error(Array.isArray(d) ? d.map((e) => `${e.loc?.at(-1)}: ${e.msg}`).join("; ") : d || res.statusText);
  }
  return body;
}

function formJson(form, numeric = []) {
  const data = Object.fromEntries(new FormData(form));
  for (const [k, v] of Object.entries(data)) {
    if (v === "") data[k] = null;
    else if (numeric.includes(k)) data[k] = Number(v);
  }
  return data;
}

async function loadHealth() {
  try {
    const h = await api("/health");
    $("#health").innerHTML = `db <b>${esc(h.database)}</b> · generation <b>${h.generation_enabled ? esc(h.generator.status) : "off"}</b> · ffmpeg <b>${h.ffmpeg ? "ok" : "missing"}</b> · v${esc(h.version)}`;
  } catch { $("#health").textContent = "API unreachable"; }
}

async function loadTemplates() {
  templates = await api("/api/templates");
  $("#template-select").innerHTML = `<option value="">None</option>` +
    templates.filter((t) => t.active).map((t) => `<option value="${t.id}">${esc(t.name)}</option>`).join("");
  $("#templates").innerHTML = templates.length ? templates.map((t) => `
    <li><b>${esc(t.name)}</b>${t.bpm_min || t.bpm_max ? ` · ${t.bpm_min ?? "?"}–${t.bpm_max ?? "?"} bpm` : ""}${t.default_key ? ` · ${esc(t.default_key)}` : ""}
    <div class="tags">${esc(t.tags || "no tags")}</div></li>`).join("")
    : `<li class="muted">No templates yet. Add one per musical lane.</li>`;
}

async function loadList() {
  const rows = await api(`/api/releases${filter ? `?status=${filter}` : ""}`);
  $("#empty").hidden = rows.length > 0;
  $("#list").innerHTML = rows.map((r) => `
    <li data-id="${r.id}" class="${r.id === selected ? "sel" : ""}" tabindex="0">
      <div style="min-width:0"><div class="t">${esc(r.title)}</div><div class="l">${esc(r.lane || "no lane")}</div></div>
      <span class="badge s-${r.status}">${r.status}</span>
    </li>`).join("");
}

function filesTable(r) {
  if (!r.assets.length) return `<p class="muted">No files yet. Upload a take (audio made elsewhere) or enable generation.</p>`;
  return `<div class="table-wrap"><table class="files">
    <thead><tr><th>Kind</th><th>File</th><th>Length</th><th>Format</th><th>LUFS</th><th>True peak</th><th>Notes</th></tr></thead>
    <tbody>${r.assets.slice().reverse().map((a) => `
      <tr>
        <td class="kind">${esc(a.kind)}</td>
        <td><a href="/api/assets/${a.id}/file" download>${esc(a.original_name || a.path.split("/").pop())}</a>
          <div class="muted" title="${esc(a.sha256)}">sha ${esc(a.sha256.slice(0, 10))} · ${esc(a.provenance?.source || "")}${a.provenance?.model ? ` · ${esc(a.provenance.model)}` : ""}</div></td>
        <td class="num">${a.duration_s ? `${Math.floor(a.duration_s / 60)}:${String(Math.round(a.duration_s % 60)).padStart(2, "0")}` : a.width ? `${a.width}×${a.height}` : "–"}</td>
        <td class="num">${a.sample_rate ? `${a.sample_rate / 1000} kHz/${a.bit_depth ?? "?"}b/${a.channels}ch` : esc(a.codec || "–")}</td>
        <td class="num">${fmt(a.integrated_lufs)}</td>
        <td class="num">${a.true_peak_dbtp === null ? "–" : `${fmt(a.true_peak_dbtp)} dBTP`}</td>
        <td class="warn">${a.qc_warnings.map(esc).join("<br>")}</td>
      </tr>`).join("")}</tbody></table></div>`;
}

function render(r) {
  const editable = ["draft", "rejected", "failed"].includes(r.status);
  const reviewable = editable || r.status === "review";
  const can = { run: r.status === "draft", decide: r.status === "review", reopen: ["rejected", "failed", "approved"].includes(r.status) };
  const notes = (r.workflow_note || "").split("\n").filter(Boolean);
  const audio = r.has_audio ? `<audio controls preload="none" src="/api/releases/${r.id}/audio"></audio>`
    : r.audio_url ? `<p><a href="${esc(r.audio_url)}" target="_blank" rel="noopener">Open generated audio</a></p>` : "";
  const dis = (on) => (on ? "" : "disabled");
  $("#detail").innerHTML = `
    <h3>${esc(r.title)}</h3>
    <div class="meta"><span class="badge s-${r.status}">${r.status}</span>
      ${esc(r.lane)} ${r.bpm ? `· ${r.bpm} bpm` : ""} ${r.musical_key ? `· ${esc(r.musical_key)}` : ""} · ${r.duration_s}s ${r.seed !== null ? `· seed ${r.seed}` : ""}
      · <a href="/api/releases/${r.id}/provenance" target="_blank">provenance</a>
      ${r.status === "approved" ? ` · <a href="/api/releases/${r.id}/package"><b>download package</b></a>` : ""}</div>
    ${r.brief ? `<h2>Brief</h2><p>${esc(r.brief)}</p>` : ""}
    <h2>Generation prompt</h2>
    <pre>${r.prompt ? esc(r.prompt) : "Not prepared yet. Run the workflow."}</pre>
    ${notes.length ? `<ul class="notes">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}

    <div class="section">
      <h2>Audio and artwork</h2>
      ${audio}
      ${filesTable(r)}
      <form id="upload" class="inline" ${reviewable ? "" : "hidden"}>
        <label>Add<select name="kind"><option value="take">Audio take</option><option value="artwork">Artwork</option></select></label>
        <label>File<input type="file" name="file" required></label>
        <button type="submit">Upload</button>
        <details style="flex-basis:100%"><summary>Provenance for audio made elsewhere</summary>
          <div class="inline">
            <label>Model<input name="model" placeholder="acestep-v15-turbo"></label>
            <label>Revision<input name="model_revision" placeholder="commit or checkpoint hash"></label>
            <label>License<input name="license" placeholder="MIT"></label>
            <label>Seed<input name="seed" inputmode="numeric"></label>
          </div>
          <label>Notes<input name="notes" placeholder="settings, edits, DAW session"></label>
        </details>
      </form>
      <div class="actions">
        <button id="export" class="ghost" ${dis(reviewable && r.assets.some((a) => a.kind === "take"))}>Export master + delivery</button>
      </div>
      <p id="file-err" class="err" role="alert"></p>
    </div>

    <div class="section">
      <h2>Release metadata</h2>
      <form id="meta">
        <label>Title<input name="title" value="${esc(r.title)}" maxlength="200" ${dis(reviewable)}></label>
        <label>Description<textarea name="description" rows="3" maxlength="5000" ${dis(reviewable)}>${esc(r.description)}</textarea></label>
        <label>Credits<textarea name="credits" rows="2" maxlength="2000" ${dis(reviewable)} placeholder="Produced and curated by …; generated with …">${esc(r.credits)}</textarea></label>
        <label>Tags<input name="tags" value="${esc(r.tags)}" maxlength="500" ${dis(reviewable)}></label>
        <button type="submit" class="ghost" ${dis(reviewable)}>Save metadata</button>
      </form>
    </div>

    <div class="section">
      <h2>Release checklist</h2>
      <div class="checklist">${Object.entries(checklistItems).map(([k, label]) => `
        <label><input type="checkbox" data-key="${k}" ${r.checklist[k] ? "checked" : ""} ${dis(reviewable)}>${esc(label)}</label>`).join("")}</div>
    </div>

    <div class="section">
      <h2>Decision</h2>
      ${r.approval_blockers.length ? `<ul class="blockers">${r.approval_blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}
      <label>Review note<textarea id="note" rows="2" placeholder="Required when rejecting"></textarea></label>
      <div class="actions">
        <button id="run" ${dis(can.run)}>Run workflow</button>
        <button id="approve" class="ok" ${dis(can.decide && !r.approval_blockers.length)}>Approve</button>
        <button id="reject" class="bad" ${dis(can.decide)}>Reject</button>
        <button id="reopen" class="ghost" ${dis(can.reopen)}>Reopen as draft</button>
        <button id="comment" class="ghost">Add comment</button>
      </div>
      <p id="act-err" class="err" role="alert"></p>
    </div>

    <div class="section">
      <h2>History</h2>
      <ul class="history">${r.events.slice().reverse().map((e) => `
        <li><b>${esc(e.action)}</b>${e.from_status !== e.to_status ? ` → ${esc(e.to_status)}` : ""}${e.note ? `: ${esc(e.note)}` : ""}
        <time>${e.actor ? `<span class="who">${esc(e.actor)}</span> · ` : ""}${new Date(e.created_at).toLocaleString()}</time></li>`).join("")}</ul>
    </div>`;

  const act = async (fn, errSel = "#act-err") => {
    try { render(await fn()); await loadList(); } catch (e) { $(errSel).textContent = e.message; }
  };
  const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body ?? {}) });
  $("#run").onclick = () => act(() => post(`/api/releases/${r.id}/run`));
  for (const action of ["approve", "reject", "reopen"]) {
    $(`#${action}`).onclick = () => act(() => post(`/api/releases/${r.id}/decision`, { action, note: $("#note").value, actor: actor() }));
  }
  $("#comment").onclick = () => act(() => post(`/api/releases/${r.id}/comments`, { note: $("#note").value, actor: actor() }));
  $("#export").onclick = (e) => {
    e.target.disabled = true; e.target.textContent = "Exporting…";
    act(() => api(`/api/releases/${r.id}/export?actor=${encodeURIComponent(actor())}`, { method: "POST" }), "#file-err")
      .finally(() => { if (document.body.contains(e.target)) { e.target.disabled = false; e.target.textContent = "Export master + delivery"; } });
  };
  $("#upload").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    fd.set("actor", actor());
    const btn = $("button[type=submit]", e.target);
    btn.disabled = true; btn.textContent = "Uploading…";
    try {
      await api(`/api/releases/${r.id}/assets`, { method: "POST", body: fd });
      await select(r.id);
    } catch (err) { $("#file-err").textContent = err.message; btn.disabled = false; btn.textContent = "Upload"; }
  };
  $("#meta").onsubmit = (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    act(() => api(`/api/releases/${r.id}`, { method: "PATCH", body: JSON.stringify(data) }));
  };
  document.querySelectorAll(".checklist input").forEach((box) => {
    box.onchange = () => act(() => api(`/api/releases/${r.id}/checklist`, {
      method: "PUT", body: JSON.stringify({ items: { [box.dataset.key]: box.checked }, actor: actor() }),
    }));
  });
}

async function select(id) {
  selected = id;
  render(await api(`/api/releases/${id}`));
  await loadList();
}

$("#list").addEventListener("click", (e) => { const li = e.target.closest("li"); if (li) select(Number(li.dataset.id)); });
$("#list").addEventListener("keydown", (e) => { const li = e.target.closest("li"); if (li && e.key === "Enter") select(Number(li.dataset.id)); });
$("#filters").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  filter = b.dataset.status;
  document.querySelectorAll("#filters button").forEach((x) => x.classList.toggle("on", x === b));
  loadList();
});
$("#create").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formJson(e.target, ["bpm", "duration_s", "template_id", "seed"]);
  if (data.duration_s === null) delete data.duration_s;
  for (const k of ["lane", "brief"]) if (data[k] === null) data[k] = "";
  try {
    const r = await api("/api/releases", { method: "POST", body: JSON.stringify(data) });
    e.target.reset(); $("#create-err").textContent = "";
    await select(r.id);
  } catch (err) { $("#create-err").textContent = err.message; }
});
$("#tpl-create").addEventListener("submit", async (e) => {
  e.preventDefault();
  const data = formJson(e.target, ["bpm_min", "bpm_max"]);
  for (const k of ["tags", "description"]) if (data[k] === null) data[k] = "";
  try {
    await api("/api/templates", { method: "POST", body: JSON.stringify(data) });
    e.target.reset(); $("#tpl-err").textContent = "";
    await loadTemplates();
  } catch (err) { $("#tpl-err").textContent = err.message; }
});

(async () => {
  checklistItems = await api("/api/checklist");
  loadHealth(); loadTemplates(); loadList();
})();
