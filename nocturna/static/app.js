const $ = (s) => document.querySelector(s);
let filter = "";
let selected = null;

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const body = res.status === 204 ? null : await res.json();
  if (!res.ok) {
    const d = body?.detail;
    throw new Error(Array.isArray(d) ? d.map((e) => `${e.loc?.at(-1)}: ${e.msg}`).join("; ") : d || res.statusText);
  }
  return body;
}

async function loadHealth() {
  try {
    const h = await api("/health");
    $("#health").innerHTML = `db <b>${esc(h.database)}</b> · generation <b>${h.generation_enabled ? esc(h.generator.status) : "off"}</b> · v${esc(h.version)}`;
  } catch { $("#health").textContent = "API unreachable"; }
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

function render(r) {
  const can = {
    run: r.status === "draft",
    decide: r.status === "review",
    reopen: ["rejected", "failed", "approved"].includes(r.status),
  };
  const notes = (r.workflow_note || "").split("\n").filter(Boolean);
  const audio = r.has_audio ? `<audio controls src="/api/releases/${r.id}/audio"></audio>`
    : r.audio_url ? `<p><a href="${esc(r.audio_url)}" target="_blank" rel="noopener">Open generated audio</a></p>`
    : `<p class="muted">No audio yet. Generation is off; add audio when a generator is enabled.</p>`;
  $("#detail").innerHTML = `
    <h3>${esc(r.title)}</h3>
    <div class="meta"><span class="badge s-${r.status}">${r.status}</span>
      ${esc(r.lane)} ${r.bpm ? `· ${r.bpm} bpm` : ""} ${r.musical_key ? `· ${esc(r.musical_key)}` : ""} · ${r.duration_s}s</div>
    ${r.brief ? `<h2>Brief</h2><p>${esc(r.brief)}</p>` : ""}
    <h2>Generation prompt</h2>
    <pre>${r.prompt ? esc(r.prompt) : "Not prepared yet. Run the workflow."}</pre>
    ${notes.length ? `<ul class="notes">${notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
    ${audio}
    <label>Review note<textarea id="note" rows="2" placeholder="Required when rejecting"></textarea></label>
    <div class="actions">
      <button id="run" ${can.run ? "" : "disabled"}>Run workflow</button>
      <button id="approve" class="ok" ${can.decide ? "" : "disabled"}>Approve</button>
      <button id="reject" class="bad" ${can.decide ? "" : "disabled"}>Reject</button>
      <button id="reopen" class="ghost" ${can.reopen ? "" : "disabled"}>Reopen as draft</button>
    </div>
    <p id="act-err" class="err" role="alert"></p>
    <h2>History</h2>
    <ul class="history">${r.events.slice().reverse().map((e) => `
      <li><b>${esc(e.action)}</b> → ${esc(e.to_status)}${e.note ? `: ${esc(e.note)}` : ""}
      <time>${new Date(e.created_at).toLocaleString()}</time></li>`).join("")}</ul>`;
  const act = async (fn) => {
    try { render(await fn()); await loadList(); } catch (e) { $("#act-err").textContent = e.message; }
  };
  $("#run").onclick = () => act(() => api(`/api/releases/${r.id}/run`, { method: "POST" }));
  for (const action of ["approve", "reject", "reopen"]) {
    $(`#${action}`).onclick = () => act(() => api(`/api/releases/${r.id}/decision`, {
      method: "POST", body: JSON.stringify({ action, note: $("#note").value }),
    }));
  }
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
  const data = Object.fromEntries(new FormData(e.target));
  for (const k of ["bpm", "duration_s"]) data[k] = data[k] ? Number(data[k]) : null;
  if (data.duration_s === null) delete data.duration_s;
  if (!data.musical_key) data.musical_key = null;
  try {
    const r = await api("/api/releases", { method: "POST", body: JSON.stringify(data) });
    e.target.reset(); $("#create-err").textContent = "";
    await select(r.id);
  } catch (err) { $("#create-err").textContent = err.message; }
});

loadHealth();
loadList();
