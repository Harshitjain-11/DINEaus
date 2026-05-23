/* ============================================================
   cart.js  —  public/js/user/cart.js
   Pure client-side logic. Zero EJS variables used here.
   Load AFTER leaflet.js and AFTER DOM is ready.
   ============================================================ */

/* ─────────────────────────────────────
   1. LEAFLET MAP + GEOLOCATION (Sidebar)
───────────────────────────────────── */
let map, marker;

document.getElementById("addressLink").addEventListener("click", function (event) {
  event.preventDefault();
  document.getElementById("sidebar").classList.add("open");
  if (!map) { initMap(); }
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(showPosition, showError);
  }
  setTimeout(() => { map.invalidateSize(); }, 400);
});

document.getElementById("closeBtn").addEventListener("click", function () {
  document.getElementById("sidebar").classList.remove("open");
});

function initMap(lat = 20.5937, lng = 78.9629, zoom = 5) {
  map = L.map("map").setView([lat, lng], zoom);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap contributors"
  }).addTo(map);
  marker = L.marker([lat, lng], { draggable: true }).addTo(map);
  marker.on("dragend", function () {
    const pos = marker.getLatLng();
    updateAddress(pos.lat, pos.lng);
  });
}

document.getElementById("getLocationBtn").addEventListener("click", function () {
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(showPosition, showError);
  } else {
    alert("Geolocation is not supported by this browser.");
  }
});

function showPosition(position) {
  const lat = position.coords.latitude;
  const lng = position.coords.longitude;
  document.getElementById("lat").value = lat;
  document.getElementById("lng").value = lng;
  map.setView([lat, lng], 16);
  marker.setLatLng([lat, lng]);
  updateAddress(lat, lng);
}

function updateAddress(lat, lng) {
  document.getElementById("lat").value = lat;
  document.getElementById("lng").value = lng;
  fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json`)
    .then(res => res.json())
    .then(data => {
      const address = data.address;
      if (address.road)     document.getElementById("street").value  = address.road;
      if (address.city)     document.getElementById("city").value    = address.city;
      if (address.state)    document.getElementById("state").value   = address.state;
      if (address.postcode) document.getElementById("pincode").value = address.postcode;
    })
    .catch(err => console.error("Error fetching address:", err));
}

function showError(error) {
  switch (error.code) {
    case error.PERMISSION_DENIED:    alert("User denied the request for Geolocation."); break;
    case error.POSITION_UNAVAILABLE: alert("Location information is unavailable.");     break;
    case error.TIMEOUT:              alert("The request to get user location timed out."); break;
    case error.UNKNOWN_ERROR:        alert("An unknown error occurred.");               break;
  }
}

/* ─────────────────────────────────────
   2. DELIVERY SLOT MODAL
───────────────────────────────────── */
function formatTime(date) {
  let h    = date.getHours();
  let m    = date.getMinutes();
  const ampm = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  m = m < 10 ? "0" + m : m;
  return h + ":" + m + " " + ampm;
}

const dateTabs = document.getElementById("dateTabs");
const today    = new Date();
const tomorrow = new Date();
tomorrow.setDate(today.getDate() + 1);

const todayBtn = document.createElement("button");
todayBtn.classList.add("date-tab", "active");
todayBtn.textContent  = "Today";
todayBtn.dataset.date = today.toDateString();
dateTabs.appendChild(todayBtn);

const tomorrowBtn = document.createElement("button");
tomorrowBtn.classList.add("date-tab");
tomorrowBtn.textContent  = "Tomorrow";
tomorrowBtn.dataset.date = tomorrow.toDateString();
dateTabs.appendChild(tomorrowBtn);

function generateSlots(selectedDate) {
  const div     = document.getElementById("timeSlots");
  div.innerHTML = "";
  const now     = new Date();
  const isToday = selectedDate.toDateString() === now.toDateString();
  const openHour = 11, closeHour = 22;

  for (let h = openHour; h < closeHour; h++) {
    const start = new Date(selectedDate); start.setHours(h, 0, 0, 0);
    const end   = new Date(selectedDate); end.setHours(h + 1, 0, 0, 0);
    if (isToday && end <= now) continue;

    const label = document.createElement("label");
    label.innerHTML = `<input type="radio" name="slot" value="${formatTime(start)} - ${formatTime(end)}">
      ${formatTime(start)} - ${formatTime(end)}`;
    div.appendChild(label);
  }
  if (!div.innerHTML) div.innerHTML = "<p style='color:red;'>No slots available</p>";
}

dateTabs.addEventListener("click", e => {
  if (e.target.classList.contains("date-tab")) {
    document.querySelectorAll(".date-tab").forEach(tab => tab.classList.remove("active"));
    e.target.classList.add("active");
    generateSlots(new Date(e.target.dataset.date));
  }
});

generateSlots(today);

const slotBtn     = document.getElementById("slotBtn");
const slotModal   = document.getElementById("slotModal");
const slotClose   = document.getElementById("slotClose");
const confirmSlot = document.getElementById("confirmSlot");
const selectedSlot = document.getElementById("selectedSlot");

slotBtn.onclick   = () => slotModal.style.display = "block";
slotClose.onclick = () => slotModal.style.display = "none";
window.onclick    = e  => { if (e.target === slotModal) slotModal.style.display = "none"; };

confirmSlot.onclick = () => {
  const slot = document.querySelector('input[name="slot"]:checked');
  if (!slot) { alert("Please select a delivery slot."); return; }

  const activeDateBtn  = document.querySelector(".date-tab.active");
  const selectedDate   = new Date(activeDateBtn.dataset.date);
  const startTime      = slot.value.split("-")[0].trim();
  const [time, ampm]   = startTime.split(" ");
  let [hour, min]      = time.split(":");

  hour = parseInt(hour);
  if (ampm === "PM" && hour !== 12) hour += 12;
  if (ampm === "AM" && hour === 12) hour = 0;
  selectedDate.setHours(hour, min, 0, 0);

  const yyyy = selectedDate.getFullYear();
  const mm   = String(selectedDate.getMonth() + 1).padStart(2, "0");
  const dd   = String(selectedDate.getDate()).padStart(2, "0");
  const hh   = String(selectedDate.getHours()).padStart(2, "0");
  const mi   = String(selectedDate.getMinutes()).padStart(2, "0");
  const finalDateTime = `${yyyy}-${mm}-${dd} ${hh}:${mi}:00`;

  document.getElementById("isScheduled").value  = "1";
  document.getElementById("scheduledFor").value = finalDateTime;

  fetch("/set-schedule", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_scheduled: true, scheduled_for: finalDateTime })
  });

  selectedSlot.innerText    = "Scheduled: " + slot.value;
  slotModal.style.display   = "none";
};

/* ─────────────────────────────────────
   3. ADDRESS SELECT / DELIVER HERE
───────────────────────────────────── */
const deliverBtns            = document.querySelectorAll(".deliver-btn");
const selectedAddressSection = document.getElementById("selectedAddressSection");
const paymentSection         = document.getElementById("paymentSection");
const changeAddressLink      = document.getElementById("changeAddress");

deliverBtns.forEach((btn) => {
  btn.addEventListener("click", function () {
    const box         = btn.closest(".address-box");
    const addressText = box.querySelector("p").innerText;
    const label       = box.querySelector("strong").innerText;
    const addressId   = btn.dataset.id;

    document.getElementById("selectedAddressId").value = addressId;

    selectedAddressSection.querySelector("strong").innerText = label;
    selectedAddressSection.querySelector("p").innerText      = addressText;
    selectedAddressSection.style.display = "block";
    paymentSection.style.display         = "block";

    document.querySelectorAll(".left .address-box").forEach(b => {
      if (b.id !== "selectedAddressSection" && b.id !== "paymentSection") {
        b.style.display = "none";
      }
    });

    window.scrollTo({ top: 0, behavior: "smooth" });
  });
});

changeAddressLink.addEventListener("click", function (e) {
  e.preventDefault();
  selectedAddressSection.style.display = "none";
  paymentSection.style.display         = "none";

  document.querySelectorAll(".left .address-box").forEach(box => {
    if (box.id !== "selectedAddressSection" && box.id !== "paymentSection") {
      box.style.display = "block";
    }
  });
});

/* ─────────────────────────────────────
   4. CART TOTAL → localStorage
───────────────────────────────────── */
window.addEventListener("DOMContentLoaded", () => {
  const totalSpan = document.querySelector(".bill span");
  if (totalSpan) {
    const total = totalSpan.textContent.replace("₹", "").trim();
    localStorage.setItem("cartTotal", total);
  }
  checkStockAndBlockPay();
});

/* ─────────────────────────────────────
   5. STOCK CHECK — called by socket too
   (defined here so socket inline script
    can call it without issues)
───────────────────────────────────── */
function checkStockAndBlockPay() {
  const hasOutOfStock = document.querySelector(".item.cart-out");
  const payBtn        = document.getElementById("payBtn");
  const msg           = document.getElementById("stockBlockMsg");
  if (!payBtn) return;

  if (hasOutOfStock) {
    payBtn.classList.add("disabled");
    msg.style.display = "block";
  } else {
    payBtn.classList.remove("disabled");
    msg.style.display = "none";
  }
}