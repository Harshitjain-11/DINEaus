 // ── Drawer ──
        const hamburger   = document.getElementById('hamburger');
        const drawer      = document.getElementById('drawer');
        const overlay     = document.getElementById('overlay');
        const drawerClose = document.getElementById('drawerClose');

        function openDrawer() {
            drawer.classList.add('open');
            overlay.classList.add('open');
            hamburger.setAttribute('aria-expanded', 'true');
            document.body.classList.add('drawer-open');
        }
        function closeDrawer() {
            drawer.classList.remove('open');
            overlay.classList.remove('open');
            hamburger.setAttribute('aria-expanded', 'false');
            document.body.classList.remove('drawer-open');
        }

        hamburger.addEventListener('click', openDrawer);
        drawerClose.addEventListener('click', closeDrawer);
        overlay.addEventListener('click', closeDrawer);
        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
        });

        // ── Scroll effect ──
        const navbar = document.getElementById('navbar');
        function handleScroll() {
            navbar.classList.toggle('scrolled', window.scrollY > 10);
        }
        window.addEventListener('scroll', handleScroll, { passive: true });
        handleScroll();

        // ── Cart badge hidden, no counter needed ──
        // (badge is display:none via CSS)

        // ── Drawer search ──
        const drawerSearchForm = document.getElementById('drawerSearchForm');
        if (drawerSearchForm) {
            drawerSearchForm.addEventListener('submit', function(e) {
                e.preventDefault();
                const q = document.getElementById('drawerSearchInput').value.trim();
                if (q) window.location.href = '/search?q=' + encodeURIComponent(q);
            });
        }