const observer = new IntersectionObserver((entries) => {
  entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visible'); } });
}, { threshold: 0.12 });
document.querySelectorAll('.fade-up').forEach(el => observer.observe(el));

setTimeout(() => {
  document.querySelectorAll('.hero .fade-up, .stats-bar .fade-up').forEach(el => el.classList.add('visible'));
}, 100);
