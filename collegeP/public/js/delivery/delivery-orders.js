


const socket = io({ transports:["websocket"] });

socket.on("orderStatusUpdate", ({ orderId, status }) => {
  const row = document.getElementById("order-row-" + orderId);
  if (!row) return;

  row.querySelector(".status").innerHTML = "<b>" + status + "</b>";
  row.dataset.status = status;
  if (status === "picked_up" || status === "out_for_delivery") {
    initMap(
      row.dataset.restLat,
      row.dataset.restLng,
      row.dataset.userLat,
      row.dataset.userLng
    );
  }

  const actionCell = row.querySelector(".action");

  if (status === "picked_up") {
    actionCell.innerHTML = `
      <form action="/delivery/order/${orderId}/out-for-delivery" method="POST">
        <button>🚚 Out For Delivery</button>
      </form>`;
  }

  if (status === "out_for_delivery") {
    actionCell.innerHTML = `
      <form action="/delivery/order/${orderId}/delivered" method="POST">
        <button>✅ Delivered</button>
      </form>`;
  }

  if (status === "delivered") {
    actionCell.innerHTML = "✔ Completed";
  }
});

async function handleDeliveryLocation(data) {
  if (!map) return;
  const { lat, lng, orderId } = data;

  if (!riderMarker) {
    riderMarker = L.marker([lat, lng], {
      icon: createBikeIcon(0)
    }).addTo(map).bindPopup("You");
  } else {
    const from = riderMarker.getLatLng();
    const to = L.latLng(lat, lng);
    const angle = getAngle(from, to);
    riderMarker.setIcon(createBikeIcon(angle));
    animateMarker(riderMarker, from, to, 1000);
    map.panTo([lat, lng], { animate: true, duration: 0.5 });
  }

  const row = document.getElementById("order-row-" + orderId);
  if (!row) return;

  const status = row.dataset.status;
  let etaData = null;

  if (status === "ready") {
    etaData = await drawRoute(lat, lng, row.dataset.restLat, row.dataset.restLng);
  }
  if (status === "picked_up" || status === "out_for_delivery") {
    etaData = await drawRoute(lat, lng, row.dataset.userLat, row.dataset.userLng);
  }
  if (etaData) {
    document.getElementById("etaText").innerText =
      `🕒 ETA: ${Math.ceil(etaData.duration / 60)} min • 📏 ${(etaData.distance / 1000).toFixed(2)} km`;
  }

  document.getElementById("mapStatus").innerText = "Live route updating...";
}

socket.on("order:deliveryLocation", handleDeliveryLocation);


socket.on("orderTaken", ({ orderId, takenBy }) => {
  if (takenBy === myPartnerId) return;
  const row = document.getElementById("order-row-" + orderId);
  if (row) row.remove();
});

let map, riderMarker, restMarker, userMarker;
let watchId = null;
let routeFittedOnce = false;
let routeLine = null;
const FAKE_MODE = false;

async function drawRoute(fromLat, fromLng, toLat, toLng) {
  const url = `https://router.project-osrm.org/route/v1/driving/${fromLng},${fromLat};${toLng},${toLat}?overview=full&geometries=geojson`;
  const res = await fetch(url);
  const data = await res.json();
  if (!data.routes || !data.routes.length) return null;
  const route = data.routes[0];
  const coords = route.geometry.coordinates.map(c => [c[1], c[0]]);
  if (routeLine) map.removeLayer(routeLine);
  routeLine = L.polyline(coords, { color: "blue", weight: 4 }).addTo(map);
  if (!routeFittedOnce) {
    map.fitBounds(routeLine.getBounds().pad(0.3));
    routeFittedOnce = true;
  }
  return { distance: route.distance, duration: route.duration };
}

function createBikeIcon(angle = 0) {
  return L.divIcon({
    className: "bike-marker",
    html: `<div style="transform: rotate(${angle}deg);">
             <img src="https://cdn-icons-png.flaticon.com/512/2972/2972185.png"
                  style="width:34px;height:34px;" />
           </div>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17]
  });
}

function getAngle(from, to) {
  const dy = to.lat - from.lat;
  const dx = to.lng - from.lng;
  return Math.atan2(dy, dx) * (180 / Math.PI);
}

function animateMarker(marker, from, to, duration = 1000) {
  const start = performance.now();
  function frame(now) {
    const progress = Math.min((now - start) / duration, 1);
    marker.setLatLng([
      from.lat + (to.lat - from.lat) * progress,
      from.lng + (to.lng - from.lng) * progress
    ]);
    if (progress < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function initMap(restLat, restLng, userLat, userLng) {
  if (!map) {
    map = L.map("map").setView([restLat, restLng], 14);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(map);
  }
  if (restMarker) map.removeLayer(restMarker);
  if (userMarker) map.removeLayer(userMarker);

  userMarker = L.marker([userLat, userLng], {
    icon: L.icon({ iconUrl: "https://cdn-icons-png.flaticon.com/512/64/64113.png", iconSize: [32, 32] })
  }).addTo(map).bindPopup("Your Location");

  restMarker = L.marker([restLat, restLng], {
    icon: L.icon({ iconUrl: "https://cdn-icons-png.flaticon.com/512/3075/3075977.png", iconSize: [32, 32] })
  }).addTo(map).bindPopup("Restaurant");

  const group = L.featureGroup([restMarker, userMarker]);
  map.fitBounds(group.getBounds().pad(0.4));
}

function startTracking(orderId) {
  socket.emit("joinOrderRoom", orderId);
  if (!navigator.geolocation) return;
  if (watchId) navigator.geolocation.clearWatch(watchId);
  watchId = navigator.geolocation.watchPosition(
    pos => {
      socket.emit("delivery:locationUpdate", {
        orderId,
        lat: pos.coords.latitude,
        lng: pos.coords.longitude
      });
    },
    err => console.log("GPS error", err),
    { enableHighAccuracy: true, maximumAge: 0, timeout: 5000 }
  );
}

function startAcceptTracking(e, orderId) {
  e.preventDefault();
  const row = document.getElementById("order-row-" + orderId);
  initMap(row.dataset.restLat, row.dataset.restLng, row.dataset.userLat, row.dataset.userLng);
  if (FAKE_MODE) {
    startFakeTest(orderId);
  } else {
    startTracking(orderId);
  }
  setTimeout(() => e.target.submit(), 300);
}

function showActive() {
  document.getElementById("activeBox").style.display = "block";
  document.getElementById("historyBox").style.display = "none";
}

function showHistory() {
  document.getElementById("activeBox").style.display = "none";
  document.getElementById("historyBox").style.display = "block";
}

function handleOutForDelivery(e, orderId) {
  e.preventDefault();
  const row = document.getElementById("order-row-" + orderId);
  initMap(row.dataset.restLat, row.dataset.restLng, row.dataset.userLat, row.dataset.userLng);
  startTracking(orderId);
  setTimeout(() => { e.target.submit(); }, 300);
  return false;
}

window.addEventListener("load", () => {
  const rows = document.querySelectorAll("tr[data-order-id]");
  rows.forEach(row => {
    const status = row.dataset.status;
    const orderId = row.dataset.orderId;
    if (status === "ready" || status === "picked_up" || status === "out_for_delivery") {
      initMap(row.dataset.restLat, row.dataset.restLng, row.dataset.userLat, row.dataset.userLng);
      if (FAKE_MODE) {
        startFakeTest(orderId);
      } else {
        startTracking(orderId);
      }
    }
  });
});

let fakeInterval = null;

function startFakeTest(orderId) {
  const row = document.getElementById("order-row-" + orderId);
  if (!row) return;
  initMap(row.dataset.restLat, row.dataset.restLng, row.dataset.userLat, row.dataset.userLng);
  routeFittedOnce = false;
  let lat = parseFloat(row.dataset.restLat) - 0.01;
  let lng = parseFloat(row.dataset.restLng) - 0.01;
  let step = 0;
  fakeInterval = setInterval(async () => {
    lat += 0.0003;
    lng += 0.0003;
    await handleDeliveryLocation({ orderId, lat, lng });
    step++;
  }, 1500);
}
