const PROVIDERS = [["groq","openai/gpt-oss-20b"],["gemini","gemini-2.5-flash"],["openrouter","meta-llama/llama-3.1-8b-instruct"],["openai","gpt-4o-mini"],["anthropic","claude-haiku-4-5"]];
let sid = null;
function fill(sel, def){ const el = document.getElementById(sel); PROVIDERS.forEach(([p,m])=>{ const o=document.createElement("option"); o.value=p; o.textContent=p; el.appendChild(o); }); }
fill("pprov"); fill("fprov");
document.getElementById("pprov").value = "groq";
document.getElementById("fprov").value = "gemini";
function syncModels(){ document.getElementById("pmodel").placeholder = PROVIDERS.find(p=>p[0]===document.getElementById("pprov").value)[1]; document.getElementById("fmodel").placeholder = PROVIDERS.find(p=>p[0]===document.getElementById("fprov").value)[1]; }
document.getElementById("pprov").onchange = syncModels; document.getElementById("fprov").onchange = syncModels; syncModels();
async function api(path, body, method){ const r = await fetch(path,{method:method||"POST",headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):null}); return r.json(); }
(async ()=>{ sid = (await api("/api/session", null)).session_id;
  try{ const h = await (await fetch("/api/health")).json();
    health.innerHTML = (h.sources||[]).map(s=>{ const st=(s.last||{}).status||"UNTESTED";
      const dot = st==="OK"?"🟢":st==="UNTESTED"?"⚪":"🔴";
      const ms = (s.last||{}).ms!=null ? " "+s.last.ms+"ms" : "";
      return "<span title='"+esc(s.role+" — "+st+ms)+"'>"+dot+" "+esc(s.name)+"</span>"; }).join(" ");
  }catch(e){ health.innerHTML = "<small>health unavailable</small>"; }
})();
document.getElementById("save").onclick = async ()=>{
  const r = await api("/api/keys",{session_id:sid,
    primary:{provider:pprov.value,model:pmodel.value||pmodel.placeholder,key:pkey.value},
    fallback:{provider:fprov.value,model:fmodel.value||fmodel.placeholder,key:fkey.value}});
  keystate.textContent = r.ok ? "keys stored server-side ("+r.primary[0]+" / "+r.fallback[0]+")" : "error: "+r.error;
  pkey.value = ""; fkey.value = "";
};
document.getElementById("clear").onclick = async ()=>{ await api("/api/session",{session_id:sid},"DELETE"); keystate.textContent = "cleared"; };
document.getElementById("run").onclick = async ()=>{
  steps.innerHTML = ""; leads.innerHTML = ""; conflicts.innerHTML = ""; dl.style.display = "none";
  const fmt = document.querySelector('input[name=fmt]:checked').value;
  const res = await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({session_id:sid,request:req.value,desired_count:+count.value,output_format:fmt,
      business_context:{business_name:bname.value,sells:sells.value,ideal_buyer:buyer.value}})});
  if(!res.ok){ steps.innerHTML = "<li>error starting run</li>"; return; }
  const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
  while(true){ const {done,value} = await reader.read(); if(done) break; buf += dec.decode(value,{stream:true});
    const parts = buf.split("\n\n"); buf = parts.pop();
    for(const p of parts){ if(!p.startsWith("data: ")) continue; const ev = JSON.parse(p.slice(6));
      if(ev.node === "result"){ finish(ev); return; }
      (ev.steps||[]).forEach(s=>{ if(![...steps.children].some(li=>li.textContent===s)){ const li=document.createElement("li"); li.textContent=s; steps.appendChild(li); } });
    } }
};
function finish(ev){
  (ev.steps||[]).forEach(s=>{ if(![...steps.children].some(li=>li.textContent===s)){ const li=document.createElement("li"); li.textContent=s; steps.appendChild(li); } });
  if(!ev.ok){ leads.innerHTML = "<p>failed: "+ev.error+"</p>"; return; }
  (ev.conflicts||[]).forEach(c=>{ const d=document.createElement("div"); d.className="card";
    d.innerHTML = "⚠️ <b>"+esc(c.lead)+"</b> — conflicting <i>"+esc(c.attribute)+"</i>: "+c.values.map(esc).join(" vs "); conflicts.appendChild(d); });
  (ev.rows||[]).forEach(r=>{ const d=document.createElement("div"); d.className="card";
    const cls = r.lead_state==="QUALIFIED"?"q":r.lead_state==="DISQUALIFIED"?"d":"u";
    d.innerHTML = "<b class='"+cls+"'>"+esc(r.lead_state)+"</b> "+esc(r.company)+" <small>"+esc(r.domain)+" · conf "+esc(r.confidence)+"</small>";
    const key = r.domain||r.company, why = (ev.why||{})[key]||[];
    if(why.length){ const det=document.createElement("details"); const sm=document.createElement("summary"); sm.textContent="Why qualified? ("+why.length+" criteria)"; det.appendChild(sm);
      why.forEach(c=>{ const p=document.createElement("p"); p.textContent=c.state+" — "+c.criterion+": "+c.reason; det.appendChild(p); }); d.appendChild(det); }
    leads.appendChild(d); });
  dl.href = "/api/download/"+ev.download; dl.style.display = "inline";
}
function esc(s){ return String(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
