/* ============================================================
   Read-only handling, mode badge
   ============================================================ */
function setMode(text,cls){ const el=document.getElementById("mode"); el.textContent=text; el.className="mode "+(cls||""); }
function setModeFor(mode){ const l=MODE_LABEL[mode]; if(l) setMode(l.text,l.cls); }
function setReadOnly(v){ RO=v; document.body.classList.toggle("ro",v); if(v) setMode("View only","ro"); if(CUR) renderMain(false); else if(document.getElementById("plistHost")) renderDashboardShell(); }
function applyRO(root){
  if(!RO) return;
  root.querySelectorAll("input:not([type=search]),textarea,select").forEach(e=>{ if(!e.closest(".fallback")) e.disabled=true; });
  root.querySelectorAll("[data-set],[data-gate],[data-delmetric]").forEach(e=>e.disabled=true);
}

/* A blocking failure screen, for when continuing would be worse than stopping.

   There is exactly one situation that warrants this: the page is served by a
   self-hosted deployment and the app cannot reach its API, or reached it and
   was refused. The tempting alternative -- quietly switch to browser-local
   storage -- is what this replaces. It stranded work in a store colleagues
   could not see, and it handed a user the server had DENIED a fully working
   private workspace.

   So: no store, no dashboard, no editing. Say which of the two happened,
   because the remedies are completely different, and offer a retry. */
function fatalError(title, detail, opts){
  const o = opts || {};
  document.body.classList.remove("home");
  document.body.classList.add("ro");
  setMode(o.mode || "Not connected", "ro");
  const rail = document.getElementById("rail");
  if(rail) rail.innerHTML = "";
  const m = document.getElementById("main");
  m.innerHTML = `
    <div class="empty-state" role="alert">
      <p class="eyebrow">Cannot start</p>
      <h1 style="margin-top:4px">${esc(title)}</h1>
      <p class="lede">${esc(detail)}</p>
      ${o.hint ? `<p class="small" style="color:var(--muted);max-width:60ch">${esc(o.hint)}</p>` : ""}
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
        <button class="btn primary" data-act="retry-boot">Try again</button>
      </div>
    </div>`;
  const retry = m.querySelector('[data-act="retry-boot"]');
  if(retry) retry.onclick = ()=>location.reload();
}

/* Say, permanently and in the layout rather than in a toast, that this mode
   stores everything in one browser.

   The storage mode is the single most consequential thing about a deployment
   of this tool and the least visible: the UI is otherwise identical whether a
   record is on a shared, access-controlled, audited server or in localStorage
   on one laptop. A user cannot be expected to infer "do not type a patient
   identifier here" from a two-word label in the header. */
/* The same, for the Claude artifact mode: where the records live, and that it is
   not the audited server. Facts from the comparison in docs/running.md; it does
   not say whether any data classification is approved. */
function showArtifactNotice(){
  if(document.getElementById("artifactNotice")) return;
  const el = document.createElement("div");
  el.id = "artifactNotice";
  el.className = "storage-warning";
  el.setAttribute("role", "note");
  el.innerHTML = `<b>Stored in this Claude artifact.</b>
    <span class="sw-detail">Records are kept in the artifact's database, not on a
    server your organization runs. Access control is only partly enforced and there
    are no version snapshots. ${SCOPE_NOTICE}
    For the audited, access-controlled workspace, deploy the server &mdash; see the
    deployment guide.</span>`;
  const header = document.querySelector("header.top");
  if(header && header.parentNode) header.parentNode.insertBefore(el, header.nextSibling);
}

/* The server mode's statement of the same scope. It used to carry none, so the
   mode that scores best on access control and audit read as the one fit for
   patient data (#34). The scope is the same in every mode (R-49): it is a policy,
   and a mistake is corrected by the purge path, which is what it was built for. */
function showScopeNotice(){
  if(document.getElementById("scopeNotice")) return;
  const el = document.createElement("div");
  el.id = "scopeNotice";
  el.className = "storage-warning";
  el.setAttribute("role", "note");
  el.innerHTML = `<b>${SCOPE_NOTICE}</b>
    <span class="sw-detail">This workspace is for review records, not clinical data.
    If patient information is entered by mistake, a project owner can purge it from
    the history; report it as your organization's policy requires.</span>`;
  const header = document.querySelector("header.top");
  if(header && header.parentNode) header.parentNode.insertBefore(el, header.nextSibling);
}

function showStorageWarning(){
  if(document.getElementById("storageWarning")) return;
  const el = document.createElement("div");
  el.id = "storageWarning";
  el.className = "storage-warning";
  el.setAttribute("role", "note");
  el.innerHTML = `<b>Saved in this browser only.</b>
    <span class="sw-detail">Nothing is sent to a server: colleagues cannot see these
    records, there is no audit log, no access control, and clearing site data
    deletes them. ${SCOPE_NOTICE}
    For a shared workspace, deploy the server &mdash; see the deployment guide.</span>`;
  const header = document.querySelector("header.top");
  if(header && header.parentNode) header.parentNode.insertBefore(el, header.nextSibling);
}
