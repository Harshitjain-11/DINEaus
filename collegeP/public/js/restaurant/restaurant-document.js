// Modal open/close logic — untouched from original
    const editBtn = document.getElementById('editCategoryBtn');
    const modal = document.getElementById('categoryModal');
    const closeModalBtn = document.getElementById('closeCategoryModal');
    const overlay = document.getElementById('modalOverlay');
    const categoryOptions = document.querySelectorAll('.category-option');
    const selectedCategorySpan = document.getElementById('selectedCategory');

    function openModal() {
      modal.classList.add('active');
      overlay.classList.add('active');
      modal.focus();
      categoryOptions.forEach(opt => {
        if(opt.dataset.category === selectedCategorySpan.textContent.trim()) {
          opt.classList.add('selected');
        } else {
          opt.classList.remove('selected');
        }
      });
    }
    function closeModal() {
      modal.classList.remove('active');
      overlay.classList.remove('active');
      editBtn.focus();
    }
    editBtn.addEventListener('click', openModal);
    closeModalBtn.addEventListener('click', closeModal);
    overlay.addEventListener('click', closeModal);
    modal.addEventListener('keydown', e => {
      if(e.key === 'Escape') closeModal();
    });
    // Select category
    categoryOptions.forEach(opt => {
      opt.addEventListener('click', function(e) {
        if(e.target.classList.contains('select-btn') || e.target === opt) {
          selectedCategorySpan.textContent = opt.dataset.category;
          closeModal();
        }
      });
      opt.addEventListener('keydown', function(e) {
        if(e.key === 'Enter' || e.key === ' ') {
          selectedCategorySpan.textContent = opt.dataset.category;
          closeModal();
        }
      });
    });