document.querySelectorAll('.button-group .option-btn').forEach(btn => {
    btn.onclick = function() {
      document.querySelectorAll('.button-group .option-btn').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
    }
  });
  // Open modal on "+" click
  document.querySelector('.category-box .edit-link').onclick = function(e) {
    e.preventDefault();
    document.getElementById('cuisineModal').style.display = 'flex';
  };
  function closeCuisineModal() {
    document.getElementById('cuisineModal').style.display = 'none';
  }
  // Add cuisine to input
  function addCuisine(name) {
    let input = document.querySelector('.category-box input');
    let val = input.value.trim();
    if(val) {
      let arr = val.split(',').map(x=>x.trim());
      if(!arr.includes(name)) arr.push(name);
      input.value = arr.filter(Boolean).join(', ');
    } else {
      input.value = name;
    }
    closeCuisineModal();
  }
  // File upload name display
  document.getElementById('menuFile').onchange = function() {
    document.getElementById('fileName').textContent = this.files[0] ? this.files[0].name : '';
  };