(() => {
  let toastTimer;

  function closeProfileDrawer() {
    const drawers = [document.getElementById('mobileDrawer'), document.getElementById('mobileMenu')];
    const hamburger = document.getElementById('hamburger');
    drawers.forEach((drawer) => drawer?.classList.remove('active'));
    if (hamburger) {
      hamburger.classList.remove('active');
      hamburger.setAttribute('aria-expanded', 'false');
      hamburger.setAttribute('aria-label', 'Open navigation menu');
    }
    document.body.style.overflow = '';
  }

  function showComingSoon(feature) {
    let toast = document.querySelector('.feature-toast');
    if (!toast) {
      toast = document.createElement('div');
      toast.className = 'feature-toast';
      toast.setAttribute('role', 'status');
      toast.setAttribute('aria-live', 'polite');
      toast.innerHTML = '<span class="feature-toast-icon" aria-hidden="true">✦</span><span class="feature-toast-message"></span>';
      document.body.appendChild(toast);
    }

    toast.querySelector('.feature-toast-message').textContent = `${feature} is coming soon.`;
    toast.classList.add('is-visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 3200);
  }

  document.addEventListener('click', (event) => {
    const link = event.target.closest('[data-coming-soon]');
    if (!link) return;
    event.preventDefault();
    showComingSoon(link.dataset.comingSoon || 'This feature');
    closeProfileDrawer();
  });
})();
