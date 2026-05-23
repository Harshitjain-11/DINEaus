 /* ── Custom Select ── */
    function toggleCsel(id) {
      const el = document.getElementById(id);
      const isOpen = el.classList.contains('open');

      // close all open dropdowns
      document.querySelectorAll('.csel.open').forEach(c => c.classList.remove('open'));

      if (!isOpen) el.classList.add('open');
    }

    function selectOpt(cselId, value, label, optEl) {
      const csel = document.getElementById(cselId);
      const hiddenInputMap = { 'csel-veg': 'val-is_veg', 'csel-avail': 'val-is_available' };
      const valSpanMap = { 'csel-veg': 'csel-veg-val', 'csel-avail': 'csel-avail-val' };

      // update label
      document.getElementById(valSpanMap[cselId]).textContent = label;

      // update hidden input
      document.getElementById(hiddenInputMap[cselId]).value = value;

      // update active class
      csel.querySelectorAll('.csel-option').forEach(o => o.classList.remove('active'));
      optEl.classList.add('active');

      // close
      csel.classList.remove('open');
    }

    // Close on outside click
    document.addEventListener('click', function(e) {
      if (!e.target.closest('.csel')) {
        document.querySelectorAll('.csel.open').forEach(c => c.classList.remove('open'));
      }
    });

    /* ── Custom File Zone ── */
    document.getElementById('image').addEventListener('change', function() {
      const zone  = document.getElementById('fileZone');
      const label = document.getElementById('fzChosen');
      const icon  = zone.querySelector('.fz-icon');

      if (this.files && this.files.length > 0) {
        zone.classList.add('has-file');
        label.textContent = '✅ ' + this.files[0].name;
        icon.textContent = '✅';
      } else {
        zone.classList.remove('has-file');
        icon.textContent = '📷';
      }
    });