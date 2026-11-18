const $ = (s, root = document) => root.querySelector(s);
let filter = "";
let selected = null;
let templates = [];
let checklistItems = {};
let generationOn = false;
let health = {};
let humanSources = {};

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
    generationOn = h.generation_enabled;
    health = h;
    const yt = h.youtube.enabled ? (h.youtube.authorized ? (h.youtube.auto_schedule ? "auto" : "on") : "no token") : "off";
    $("#health").innerHTML = `DB <b>${esc(h.database)}</b> · MUSIC GEN <b>${h.generation_enabled ? esc(h.generator.status) : "off"}</b> · YOUTUBE <b>${esc(yt)}</b> · FFMPEG <b>${h.ffmpeg ? "ok" : "missing"}</b> · v${esc(h.version)}`;
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
      <span class="time">${esc(r.capture_time || "--:--")}</span>
      <div style="min-width:0;flex:1"><div class="t">${esc(r.title)}</div><div class="l">${esc(r.catalog_no)} · ${esc(r.lane || "no lane")}</div></div>
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
  const cover = [...r.assets].reverse().find((a) => a.kind === "artwork");
  const layers = r.assets.filter((a) => a.kind === "human");
  $("#detail").innerHTML = `
    <div class="head-row">
      ${cover ? `<img class="cover-thumb" src="/api/assets/${cover.id}/file" alt="Cover of ${esc(r.title)}">` : ""}
      <div style="min-width:0">
        <div class="catalog">${esc(r.catalog_no)}${r.capture_time ? ` · CAPTURED ${esc(r.capture_time)}` : ""}</div>
        <h3>${esc(r.title)}</h3>
      </div>
    </div>
    <div class="meta"><span class="badge s-${r.status}">${r.status}</span>
      ${esc(r.lane)} ${r.bpm ? `· ${r.bpm} bpm` : ""} ${r.musical_key ? `· ${esc(r.musical_key)}` : ""} · ${r.duration_s}s ${r.seed !== null ? `· seed ${r.seed}` : ""}
      · <a href="/api/releases/${r.id}/provenance" target="_blank">provenance</a>
      · <a href="/api/releases/${r.id}/card" target="_blank">provenance card</a>
      ${r.status === "approved" ? ` · <a href="/api/releases/${r.id}/package"><b>download package</b></a>` : ""}</div>
    ${r.brief ? `<h2>Brief</h2><p>${esc(r.brief)}</p>` : ""}
    <h2>Generation prompt</h2>
    <pre>${r.prompt ? esc(r.prompt) : "Not prepared yet. Run the workflow."}</pre>
    ${notes.length ? `<ul class="notes">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}

    <div class="human">
      <h2>Human layer · ${layers.length ? `${layers.length} attached` : "required before approval"}</h2>
      ${layers.length ? `<ul class="uploads">${layers.map((a) => `<li>${esc(a.provenance.title || a.original_name)} · ${esc(a.provenance.source_type)} · ${esc(a.provenance.license)}</li>`).join("")}</ul>` : `<p class="muted">Add a real recording (yours, or a licensed human-made sound) to mix into this track.</p>`}
      ${r.human_credits.length ? `<pre>${r.human_credits.map(esc).join("\n")}</pre>` : ""}
      <form id="human" class="inline" ${reviewable ? "" : "hidden"}>
        <label>Source<select name="source_type">${Object.entries(humanSources).map(([k, v]) => `<option value="${k}">${esc(v)}</option>`).join("")}</select></label>
        <label>File<input type="file" name="file" required></label>
        <label>Title<input name="sound_title" placeholder="Rain on the depot roof"></label>
        <label>Author<input name="author" placeholder="you, the recordist or the vendor"></label>
        <label>Licence<input name="license" placeholder="CC0, CC BY 4.0, royalty-free"></label>
        <label>Source link<input name="source_url" placeholder="https://"></label>
        <button type="submit">Add human layer</button>
      </form>
      ${reviewable && health.freesound_enabled ? `
      <form id="fs-search" class="inline">
        <label>Search Freesound (CC0 and CC BY only)<input name="q" placeholder="rain on window, cimbalom, train at night"></label>
        <button type="submit" class="ghost">Search</button>
      </form>
      <ul id="fs-results" class="results"></ul>` : ""}
      <p id="human-err" class="err" role="alert"></p>
    </div>

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
        <button id="cover" class="ghost" ${dis(reviewable)}>Make Infrared cover</button>
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
        <label>Capture time (HH:MM, shown on the cover)<input name="capture_time" value="${esc(r.capture_time || "")}" pattern="([01][0-9]|2[0-3]):[0-5][0-9]" ${dis(reviewable)}></label>
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
      <h2>YouTube</h2>
      ${r.uploads.length ? `<ul class="uploads">${r.uploads.map((u) => `<li class="${u.status}">${esc(u.kind)} · ${esc(u.status)} · goes public ${new Date(u.publish_at).toLocaleString()}${u.video_id ? ` · <a href="https://studio.youtube.com/video/${esc(u.video_id)}/edit" target="_blank" rel="noopener">open in Studio</a>` : ""}${u.error ? `<br>${esc(u.error)}` : ""}${u.status === "failed" ? ` <button class="ghost retry" data-id="${u.id}">Retry</button>` : ""}</li>`).join("")}</ul>` : `<p class="muted">${health.youtube?.enabled ? "Not scheduled yet." : "YouTube uploads are off (see docs/youtube.md)."}</p>`}
      <div class="actions"><button id="yt" class="ghost" ${dis(r.status === "approved" && health.youtube?.enabled)}>Schedule private upload + Short</button></div>
      <p class="muted">Uploads are private until their slot, with the AI disclosure always set.</p>
      <p id="yt-err" class="err" role="alert"></p>
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
  $("#run").onclick = (e) => {
    e.target.disabled = true;
    e.target.textContent = generationOn ? "Generating… (minutes on CPU)" : "Running…";
    act(() => post(`/api/releases/${r.id}/run`));
  };
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
  $("#cover").onclick = (e) => {
    e.target.disabled = true; e.target.textContent = "Rendering…";
    act(() => api(`/api/releases/${r.id}/cover?actor=${encodeURIComponent(actor())}`, { method: "POST" }), "#file-err");
  };
  $("#yt").onclick = (e) => {
    e.target.disabled = true; e.target.textContent = "Scheduling… (rendering and uploading)";
    api(`/api/releases/${r.id}/youtube`, { method: "POST", body: JSON.stringify({ actor: actor() }) })
      .then(() => select(r.id)).catch((err) => { $("#yt-err").textContent = err.message; });
  };
  document.querySelectorAll(".retry").forEach((b) => {
    b.onclick = () => api(`/api/youtube/uploads/${b.dataset.id}/retry`, { method: "POST" })
      .then(() => select(r.id)).catch((err) => { $("#yt-err").textContent = err.message; });
  });
  $("#human").onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    fd.set("kind", "human"); fd.set("actor", actor());
    try { await api(`/api/releases/${r.id}/assets`, { method: "POST", body: fd }); await select(r.id); }
    catch (err) { $("#human-err").textContent = err.message; }
  };
  if ($("#fs-search")) {
    $("#fs-search").onsubmit = async (e) => {
      e.preventDefault();
      try {
        const rows = await api(`/api/freesound/search?q=${encodeURIComponent(new FormData(e.target).get("q"))}`);
        $("#fs-results").innerHTML = rows.map((x) => `<li class="${x.usable ? "" : "blocked"}">
          <span><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.name)}</a> · ${esc(x.username)} · ${x.usable ? esc(x.license) : "not allowed (NC or Sampling+)"}</span>
          ${x.usable ? `<button class="ghost" data-sound="${x.id}">Use</button>` : ""}</li>`).join("") || `<li class="muted">No results.</li>`;
        document.querySelectorAll("#fs-results button").forEach((b) => {
          b.onclick = () => act(async () => {
            await post(`/api/releases/${r.id}/human/freesound`, { sound_id: Number(b.dataset.sound), actor: actor() });
            return api(`/api/releases/${r.id}`);
          }, "#human-err");
        });
      } catch (err) { $("#human-err").textContent = err.message; }
    };
  }
  $("#meta").onsubmit = (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target));
    if (!data.capture_time) delete data.capture_time;
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
  humanSources = await api("/api/human/sources");
  await loadHealth(); loadTemplates(); loadList();
})();
