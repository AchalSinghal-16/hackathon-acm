(function() {
  const btn = document.querySelector('.menu-btn');
  const links = document.getElementById('links');

  if (btn && links) {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = links.classList.toggle('open');
      btn.setAttribute('aria-expanded', isOpen);
      btn.classList.toggle('active', isOpen);
    });

    document.addEventListener('click', (e) => {
      if (links.classList.contains('open') && !links.contains(e.target) && !btn.contains(e.target)) {
        links.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
        btn.classList.remove('active');
      }
    });

    links.querySelectorAll('a').forEach(a => {
      a.addEventListener('click', () => {
        links.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
        btn.classList.remove('active');
      });
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && links.classList.contains('open')) {
        links.classList.remove('open');
        btn.setAttribute('aria-expanded', 'false');
        btn.classList.remove('active');
      }
    });
  }

  // Flash toasts auto-fade
  setTimeout(() => {
    document.querySelectorAll('.toast').forEach(t => {
      t.style.opacity = '0';
      setTimeout(() => t.remove(), 400);
    });
  }, 5000);
})();
