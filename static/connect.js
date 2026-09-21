// /connect page: host picker, token issuance, client-side config downloads. Vanilla only.
document.querySelectorAll("#host-pick .host").forEach(btn => btn.addEventListener("click", () => {
  document.querySelectorAll("#host-pick .host").forEach(b => b.classList.remove("on"));
  document.querySelectorAll(".guide").forEach(g => g.classList.remove("on"));
  btn.classList.add("on");
  document.getElementById(btn.dataset.g)?.classList.add("on");
}));

document.getElementById("tget").addEventListener("click", async () => {
  const out = document.getElementById("token-out");
  out.style.display = "block";
  out.textContent = "issuing…";
  try {
    const r = await (await fetch("/api/token/request", {method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({label: document.getElementById("tlabel").value || "website"})})).json();
    if (!r.ok) { out.textContent = "refused: " + (r.error || "unknown"); return; }
    out.innerHTML = "";
    const b = document.createElement("b");
    b.textContent = r.token;
    const p = document.createElement("p");
    p.textContent = "Copy now — shown once. " + r.cap_per_day + " requests/day.";
    const c = document.createElement("button");
    c.textContent = "Copy token"; c.className = "btn small"; c.type = "button";
    c.onclick = async () => {
      try { await navigator.clipboard.writeText(r.token); c.textContent = "Copied"; }
      catch (e) { c.textContent = "Select manually"; }
    };
    out.append(b, p, c);
  } catch (e) { out.textContent = "server unreachable"; }
});

function download(name, obj) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(obj, null, 2)], {type: "application/json"}));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
// ponytail: local stdio paths assume a repo checkout beside the user; remote users take the token path instead
const STDIO = {"command": "python", "args": ["-m", "reaver_mcp.server", "--transport", "stdio"]};
document.getElementById("dl-desktop")?.addEventListener("click", () =>
  download("claude_desktop_config.json", {"mcpServers": {"reaver": STDIO}}));
document.getElementById("dl-cursor")?.addEventListener("click", () =>
  download("cursor-mcp.json", {"mcpServers": {"reaver": STDIO}}));
document.getElementById("dl-minimax")?.addEventListener("click", () =>
  download("minimax-mcp.json", {"mcpServers": {"reaver": STDIO}}));
