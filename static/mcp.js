// MCP docs page: host tabs, copy buttons, tool reference, live status. Vanilla only.
document.querySelectorAll("#host-tabs .tab").forEach(btn => btn.addEventListener("click", () => {
  document.querySelectorAll("#host-tabs .tab").forEach(b => b.classList.remove("on"));
  document.querySelectorAll(".pane").forEach(p => p.classList.remove("on"));
  btn.classList.add("on");
  document.getElementById(btn.dataset.pane)?.classList.add("on");
}));
document.querySelectorAll(".copy").forEach(btn => btn.addEventListener("click", async () => {
  const code = btn.parentElement.querySelector("code")?.innerText || "";
  try { await navigator.clipboard.writeText(code); btn.textContent = "Copied"; }
  catch (e) { btn.textContent = "Select manually"; }
  setTimeout(() => { btn.textContent = "Copy"; }, 1500);
}));

const TOOLS = [
  ["prospect", "(request, desired_count=20, output_format=csv, business_context={})",
   "Full hunt end-to-end. Returns leads + rejected-with-reasons + shortfall + quota."],
  ["discover_leads", "(request, desired_count=20)",
   "Candidate pool from the routed search mesh. Cheap, wide, cached."],
  ["research_target", "(name, domain='')",
   "Deep page fetch (robots-gated) + structured attribute extraction for one entity."],
  ["enrich_lead", "(name, domain='')",
   "Apollo firmographics + Hunter email signal. Partial results reported honestly."],
  ["qualify_lead", "(name, criteria[], evidence[])",
   "Code-graded PASS / FAIL / UNKNOWN per criterion with citations."],
  ["verify_evidence", "(evidence[], ttl_days=90)",
   "Freshness, tier-blind conflicts, staleness per attribute."],
  ["deduplicate_leads", "(leads[])",
   "Entity resolution: merges duplicates, unions evidence, flags disagreement UNCERTAIN."],
  ["refresh_leads", "(leads[], criteria[]=[])",
   "Forced refetch + change detection. REFRESHED / FRESH / STALE / GONE."],
  ["export_leads", "(leads[], output_format=csv)",
   "CSV (default, HubSpot-mappable) or JSON. Nothing else."],
  ["doctor", "()",
   "Source registry: roles, key presence, last-known latency. Burns no quota."],
];
document.getElementById("tools").innerHTML = TOOLS.map(([n, sig, d], i) =>
  `<div class="card tool reveal in"><h3>${String(i + 1).padStart(2, "0")} · ${n}</h3>` +
  `<code class="sig">${n}${sig}</code><p class="ret">${d}</p></div>`).join("");

(async () => {
  try {
    const h = await (await fetch("/api/health")).json();
    const n = (h.sources || []).length;
    document.getElementById("live").innerHTML =
      `This server reports <b class="dotok">${n} sources live</b> right now.`;
  } catch (e) {
    document.getElementById("live").innerHTML =
      `Start the local server to see <b class="dotbad">live status here</b>.`;
  }
})();
