 const socket = io({
    transports: ["websocket"],
    upgrade: false
  });

  const rElem = document.getElementById("RESTAURANT_ID");
  const restaurantId = rElem ? rElem.value : "";
 const ordersTable = document.getElementById("ordersTable");
const noOrdersMsg = document.getElementById("noOrdersMsg");

function toggleOrdersVisibility() {
  const rowsCount = ordersTable.querySelectorAll("tr").length;

  // only header row present
  if (rowsCount <= 1) {
    ordersTable.style.display = "none";
    noOrdersMsg.style.display = "block";
  } else {
    ordersTable.style.display = "table";
    noOrdersMsg.style.display = "none";
  }
}

document.addEventListener("DOMContentLoaded", toggleOrdersVisibility);


function createOrderRowHTML(o){

  let itemsHtml = "<ul style='margin:0;padding-left:18px'>";
  (o.items || []).forEach(it => {
    itemsHtml += `<li>${it.item_name} × ${it.quantity}</li>`;
  });
  itemsHtml += "</ul>";

  return `
    <tr id="order-row-${o.id}">
      <td>${o.id}</td>

      <td>${itemsHtml}</td>

      <td>₹${Number(o.total_price).toFixed(2)}</td>

      <td style="font-weight:600;color:#d35400;">
        PENDING
      </td>

      <!-- ✅ DELIVERY PARTNER COLUMN -->
      <td>
        <span style="color:gray;">Not assigned</span>
      </td>

      <!-- ✅ ACTION COLUMN -->
      <td>
        <form action="/restaurant-admin/order/${o.id}/accept" method="POST" style="display:inline;">
          <button>Accept</button>
        </form>
        <form action="/restaurant-admin/order/${o.id}/reject" method="POST" style="display:inline;">
          <button>Reject</button>
        </form>
      </td>
    </tr>
  `;
}


  // play sound
  const sound = document.getElementById("newOrderSound");
  function playSound(){ if(sound) sound.play().catch(e=>console.log("sound err",e)); }

  socket.on("connect", () => {
  console.log("✅ Restaurant socket connected:", socket.id);
  console.log("🏪 Joining restaurant room:", restaurantId);

  if (restaurantId) {
    socket.emit("joinRestaurantRoom", String(restaurantId));
  } else {
    console.error("❌ restaurantId missing in EJS");
  }
});

  // ✅ BOOKING STATUS UPDATE (USER CANCEL / RESTAURANT ACTION)
socket.on("bookingStatusUpdate", (data) => {
  console.log("📢 Booking status update:", data);

  const { bookingId, status } = data;

  const row = document.querySelector(`tr[data-booking-id="${bookingId}"]`);
  if (!row) return;

  if (["cancelled", "rejected", "completed"].includes(status)) {
    row.remove();

    // ✅ check if any active rows left
    const remaining =
      document.querySelectorAll("#activeBookingsTable tr[data-booking-id]")
        .length;

    if (remaining === 0) {
      document.getElementById("activeBookingsTable").style.display = "none";
      const msg = document.getElementById("noBookingsMsg");
      if (msg) msg.style.display = "block";
    }

    return;
  }

  // update status text
  const statusCell = row.querySelector(".booking-status");
  if (statusCell) statusCell.innerText = status;
});

socket.on("newOrder", (order) => {
  console.log("🛵 New order received:", order);

  const temp = document.createElement("tbody");
  temp.innerHTML = createOrderRowHTML(order);
  const row = temp.firstElementChild;

  ordersTable.appendChild(row);

  toggleOrdersVisibility();   // ✅ IMPORTANT

  flashHighlight(order.id);
  playSound();
});


// 🔥 NEW TABLE BOOKING REALTIME
socket.on("newBooking", (booking) => {
  console.log("🪑 New booking received:", booking);

  // simplest safe way
  location.reload();
});

socket.on("orderStatusUpdate", ({ orderId, status }) => {
  console.log("🔄 Order status update:", orderId, status);

  const row = document.getElementById("order-row-" + orderId);
  if (!row) return;

  const statusCell = row.children[3];
  const actionCell = row.children[5];

  // statusCell.innerText = status;
  statusCell.innerText = status.replaceAll("_"," ").toUpperCase();
  // ✅ enable complete button only when delivered by delivery boy
  if (status === "delivered") {
    const btn = document.getElementById("complete-btn-" + orderId);
    if (btn) {
      btn.disabled = false;
      btn.style.opacity = "1";
      btn.style.cursor = "pointer";
    }
  }
  
  if (status === "accepted") {
    actionCell.innerHTML = `
      <form action="/restaurant-admin/order/${orderId}/preparing" method="POST">
        <button>Start Preparing</button>
      </form>`;
  }
  else if (status === "preparing") {
    actionCell.innerHTML = `
      <form action="/restaurant-admin/order/${orderId}/ready" method="POST">
        <button>Mark Ready</button>
      </form>`;
  }
  else if (status === "ready") {
    actionCell.innerHTML = `
      <form action="/restaurant-admin/order/${orderId}/completed" method="POST">
        <button id="complete-btn-${orderId}" disabled style="opacity:0.5;cursor:not-allowed;">
          Completed
        </button>
      </form>`;
  }
  else if (status === "completed" || status === "rejected") {
    row.remove();

    toggleOrdersVisibility(); 
  }

  flashHighlight(orderId);
});

  // small flash animation
  function flashHighlight(orderId){
    const row = document.getElementById("order-row-" + orderId);
    if(!row) return;
    row.style.transition = "background-color 0.3s ease";
    row.style.backgroundColor = "#e6ffe6"; // light green
    setTimeout(()=> row.style.backgroundColor = "", 1500);
  }
socket.on("deliveryAssigned", data => {
  console.log("🛵 Delivery assigned:", data);

  const row = document.getElementById("order-row-" + data.orderId);
  if (!row) return;

  const cell = row.children[4]; // delivery column index
  cell.innerHTML = `🛵 <b>${data.name}</b><br>📞 ${data.phone}`;
});


    socket.on("newOrderPlaced", (data) => {
        console.log("New Order Received", data);

        const audio = document.getElementById("newOrderSound");

        audio.play().catch(err => {
            console.log("Autoplay blocked, playing muted first...", err);
            audio.muted = true;
            audio.play().then(() => {
                audio.muted = false;
            });
        });

        // Optionally reload section
        // location.reload();
    });

function showTab(tab){
  localStorage.setItem("restaurantActiveTab", tab); 
  document.getElementById("ordersTab").style.display =
    tab === "orders" ? "block" : "none";

  document.getElementById("bookingsTab").style.display =
    tab === "bookings" ? "block" : "none";
}
document.addEventListener("DOMContentLoaded", () => {
  const savedTab = localStorage.getItem("restaurantActiveTab");

  if (savedTab) {
    showTab(savedTab);
  } else {
    showTab("orders"); // default
  }
});


function showBookingHistory(){
  document.getElementById("activeBookingsBox").style.display = "none";
  document.getElementById("bookingHistoryBox").style.display = "block";
}

function showActiveBookings(){
  document.getElementById("activeBookingsBox").style.display = "block";
  document.getElementById("bookingHistoryBox").style.display = "none";
}