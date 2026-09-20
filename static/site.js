// REAVER site chrome: theme, forge loader, reveals, spark field, counters, magnetic CTAs. Vanilla only.
try {
  if (localStorage.getItem("reaver-theme") === "bright") document.documentElement.dataset.theme = "bright";
} catch (e) {}
document.querySelectorAll("[data-theme-btn]").forEach(btn => btn.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "bright" ? "" : "bright";
  if (next) document.documentElement.dataset.theme = next;
  else delete document.documentElement.dataset.theme;
  try { localStorage.setItem("reaver-theme", next || "dark"); } catch (e) {}
}));
const WORDS = ["Heating", "Hammering", "Quenching", "Honing"];
let wi = 0;
const wordTimer = setInterval(() => {
  const el = document.getElementById("forge-word");
  if (!el || document.getElementById("loader")?.classList.contains("done")) { clearInterval(wordTimer); return; }
  el.textContent = WORDS[++wi % WORDS.length];
}, 450);
addEventListener("load", () => setTimeout(
  () => document.getElementById("loader")?.classList.add("done"), 900));

const io = new IntersectionObserver(es => es.forEach(e =>
  e.isIntersecting && (e.target.classList.add("in"), io.unobserve(e.target))), {threshold: .12});
document.querySelectorAll(".reveal").forEach(el => io.observe(el));

// counters
const cio = new IntersectionObserver(es => es.forEach(e => {
  if (!e.isIntersecting) return;
  cio.unobserve(e.target);
  const end = +e.target.dataset.count, t0 = performance.now();
  const tick = t => {
    const p = Math.min((t - t0) / 1200, 1);
    e.target.textContent = Math.round(end * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}), {threshold: .4});
document.querySelectorAll("[data-count]").forEach(el => cio.observe(el));

// illustrative run transcript: real engine step names, looped demo (labeled on-page)
(() => {
  const screen = document.getElementById("term-screen");
  if (!screen) return;
  const lines = [
    ["dim", "$ reaver prospect \"20 bakeries in Ahmedabad\""],
    ["", "compile:ok · 3 criteria"],
    ["", "plan:6 queries"],
    ["ok", "discover:41 via tavily+serper+serpapi"],
    ["", "research:9 new · verify:ok"],
    ["ok", "qualify:+15 · dedupe:15->14"],
    ["warn", "deliver 12 · reject 1 · shortfall 8"],
    ["ok", "export:csv ✓"],
  ];
  let i = 0;
  setInterval(() => {
    const [cls, text] = lines[i % lines.length];
    if (i % lines.length === 0) screen.innerHTML = "";
    const div = document.createElement("div");
    div.className = "ln " + cls;
    div.textContent = text;
    screen.appendChild(div);
    i++;
  }, 900);
})();

// strike rail buttons
document.getElementById("rail-l")?.addEventListener("click", () =>
  document.getElementById("rail")?.scrollBy({left: -350, top: 0, behavior: "smooth"}));
document.getElementById("rail-r")?.addEventListener("click", () =>
  document.getElementById("rail")?.scrollBy({left: 350, top: 0, behavior: "smooth"}));

// verdict tabs
document.querySelectorAll(".vtab").forEach(btn => btn.addEventListener("click", () => {
  document.querySelectorAll(".vtab").forEach(b => b.classList.remove("on"));
  document.querySelectorAll(".vpane").forEach(p => p.classList.remove("on"));
  btn.classList.add("on");
  document.getElementById("v-" + btn.dataset.v)?.classList.add("on");
}));

// magnetic CTAs (hover-only, no cursor replacement)
if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
  document.querySelectorAll("[data-mag]").forEach(el => {
    el.addEventListener("mousemove", e => {
      const r = el.getBoundingClientRect();
      el.style.transform = `translate(${(e.clientX - r.left - r.width / 2) / 8}px, ${(e.clientY - r.top - r.height / 2) / 8}px)`;
    });
    el.addEventListener("mouseleave", () => { el.style.transform = ""; });
  });
}

// spark field: embers drift up, flee the pointer
(() => {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const cv = document.getElementById("stars");
  if (!cv) return;
  const ctx = cv.getContext("2d");
  let W, H, mx = -9999, my = -9999;
  const N = 70, ps = [];
  const size = () => { W = cv.width = innerWidth; H = cv.height = innerHeight; };
  size(); addEventListener("resize", size);
  addEventListener("pointermove", e => { mx = e.clientX; my = e.clientY; });
  for (let i = 0; i < N; i++) ps.push({x: Math.random(), y: Math.random(), s: Math.random() * 2 + .4, v: Math.random() * .0009 + .0002, hue: Math.random() < .75 ? "242,183,5" : "230,46,43"});
  // ponytail: fixed 70 embers, no density scaling; per-device tuning only if jank is measured
  (function frame() {
    ctx.clearRect(0, 0, W, H);
    for (const p of ps) {
      p.y -= p.v;
      if (p.y < -0.02) { p.y = 1.02; p.x = Math.random(); }
      let x = p.x * W, y = p.y * H;
      const dx = x - mx, dy = y - my, d = Math.hypot(dx, dy);
      if (d < 130) { x += dx / d * 26; y += dy / d * 26; }
      ctx.fillStyle = `rgba(${p.hue},${.25 + p.s * .2})`;
      ctx.beginPath(); ctx.arc(x, y, p.s, 0, 7); ctx.fill();
    }
    requestAnimationFrame(frame);
  })();
})();
