// shared site chrome: loader + scroll reveals. No frameworks.
addEventListener("load", () => setTimeout(
  () => document.getElementById("loader")?.classList.add("done"), 650));
const io = new IntersectionObserver(es => es.forEach(e =>
  e.isIntersecting && (e.target.classList.add("in"), io.unobserve(e.target))), {threshold: .12});
document.querySelectorAll(".reveal").forEach(el => io.observe(el));
