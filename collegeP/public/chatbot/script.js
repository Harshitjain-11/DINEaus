 const input = document.getElementById("user-input");
const btn = document.getElementById("send-btn");
const micBtn = document.getElementById("mic-btn");
const messages = document.getElementById("chat-messages");
const chatToggle = document.getElementById("chat-toggle");
const chatContainer = document.getElementById("chat-container");
const minimizeBtn = document.getElementById("minimize-btn");
const resetBtn = document.getElementById("reset-btn");

let isSending = false;
let activeCartCardEl = null; // tracks live cart card — old ones get removed
let lastSubmittedMessage = "";
let lastSubmittedAt = 0;

function setChatbotOpen(isOpen) {
  chatContainer.classList.toggle("open", isOpen);
  chatToggle.classList.toggle("active", isOpen);
  chatToggle.setAttribute("aria-expanded", String(isOpen));
}

// ===== FOOD EMOJIS =====
const FOOD_EMOJIS = {
  pizza: '🍕', burger: '🍔', pasta: '🍝', salad: '🥗', soup: '🍲',
  sandwich: '🥪', taco: '🌮', sushi: '🍣', ramen: '🍜', rice: '🍚',
  chicken: '🍗', steak: '🥩', fish: '🐟', shrimp: '🍤', wrap: '🌯',
  fries: '🍟', nachos: '🧀', wings: '🍗', ribs: '🍖', noodle: '🍜',
  dosa: '🫓', idli: '🫓', biryani: '🍛', curry: '🍛', paneer: '🧀',
  naan: '🫓', dal: '🫕', samosa: '🥟', chai: '☕', coffee: '☕',
  tea: '🍵', juice: '🧃', coke: '🥤', water: '💧', lassi: '🥛',
  icecream: '🍦', cake: '🎂', brownie: '🍫', gulab: '🍮', halwa: '🍮',
  momos: '🥟', chowmein: '🍜', thali: '🍽️', pavbhaji: '🍽️',
  default: '🍽️'
};

function getFoodEmoji(itemName) {
  const lower = itemName.toLowerCase();
  for (const [key, emoji] of Object.entries(FOOD_EMOJIS)) {
    if (lower.includes(key)) return emoji;
  }
  return FOOD_EMOJIS.default;
}

// ===== APPEND PLAIN TEXT MESSAGE =====
function appendMessage(sender, text) {
  const wrapper = document.createElement("div");
  wrapper.className = sender === "user" ? "message user-msg" : "message bot-msg";

  if (sender === "bot") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.innerHTML = `<img src="/chatbot/assets/bot-face.png" alt="DineBot">`;
    wrapper.appendChild(avatar);
  }

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  if (sender === "bot") {
    bubble.style.whiteSpace = "pre-line";
  }
  bubble.textContent = text;

  const time = document.createElement("div");
  time.className = "time";
  time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  wrapper.appendChild(bubble);
  wrapper.appendChild(time);
  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
}

// ===== APPEND RICH CARD =====
function appendCard(cardHTML) {
  const wrapper = document.createElement("div");
  wrapper.className = "message bot-msg";
  wrapper.style.flexDirection = "column";
  wrapper.style.alignItems = "flex-start";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.style.marginBottom = "6px";
  avatar.innerHTML = `<img src="/chatbot/assets/bot-face.png" alt="DineBot">`;

  const cardWrapper = document.createElement("div");
  cardWrapper.style.maxWidth = "90%";
  cardWrapper.style.width = "100%";
  cardWrapper.innerHTML = cardHTML;

  const time = document.createElement("div");
  time.className = "time";
  time.style.marginLeft = "0";
  time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  wrapper.appendChild(avatar);
  wrapper.appendChild(cardWrapper);
  wrapper.appendChild(time);
  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;

  return wrapper; // returned so stale cards can be removed
}

// ===== RENDER RESTAURANT CARDS =====
// Uses real image_url from DB (Swiggy CDN URLs) — emoji fallback only if missing
function renderRestaurantCards(restaurants) {
  const html = `
    <div class="restaurant-cards">
      ${restaurants.map((r, i) => `
        <div class="restaurant-card">
          <div class="restaurant-card-banner" style="
            background: #1a1a1a;
            overflow: hidden;
            position: relative;
            height: 100px;
          ">
            ${r.image_url
              ? `<img
                   src="${r.image_url}"
                   alt="${r.name}"
                   loading="lazy"
                   style="width:100%;height:100%;object-fit:cover;"
                   onerror="this.style.display='none';this.insertAdjacentHTML('afterend','<span style=\\'font-size:30px;position:absolute;top:50%;left:50%;transform:translate(-50%,-50%)\\'>🍽️</span>')"
                 >`
              : `<span style="font-size:30px;position:absolute;top:50%;left:50%;transform:translate(-50%,-50%)">🍽️</span>`
            }
            <span style="
              position:absolute;top:8px;right:8px;
              background:rgba(0,0,0,0.55);
              padding:2px 8px;border-radius:20px;
              font-size:11px;color:#fff;font-weight:600;
            ">#${i + 1}</span>
          </div>
          <div class="restaurant-card-body">
            <div class="restaurant-card-title">${r.name}</div>
            <div class="restaurant-card-meta">
              <span class="restaurant-meta-item">📍 ${r.location || 'Gwalior'}</span>
              <span class="restaurant-meta-item">⭐ ${(4 + Math.random()).toFixed(1)}</span>
              <span class="restaurant-meta-item">🕐 25-35 min</span>
            </div>
            <button class="restaurant-select-btn"
              onclick="selectRestaurant(${r.id}, '${r.name.replace(/'/g, "\\'")}')">
              Select Restaurant <span>→</span>
            </button>
          </div>
        </div>
      `).join('')}
    </div>
  `;

  appendMessage("bot", "🍽️ Here are our restaurants — pick your favourite!");
  appendCard(html);
}

// ===== RENDER MENU CARDS =====
function renderMenuCards(menuItems) {
  const items = Array.isArray(menuItems) ? menuItems : [];

  const html = `
    <div style="width:100%">
      <div class="menu-section-title">🍴 Today's Menu</div>
      <div class="menu-grid">
        ${items.map(item => {
          const name  = item.item_name || item.name || 'Item';
          const price = item.price || 0;
          const emoji = getFoodEmoji(name);
          const safeName = name.replace(/'/g, "\\'");
          return `
            <div class="menu-item-card" onclick="orderItem('${safeName}')">
              <div class="menu-item-left">
                <div class="menu-item-icon">${emoji}</div>
                <div class="menu-item-info">
                  <div class="menu-item-name">${name.charAt(0).toUpperCase() + name.slice(1)}</div>
                  <div class="menu-item-desc">Freshly prepared</div>
                </div>
              </div>
              <div class="menu-item-right">
                <div class="menu-item-price">₹${price}</div>
                <button class="menu-add-btn" onclick="event.stopPropagation(); orderItem('${safeName}')">+</button>
              </div>
            </div>
          `;
        }).join('')}
      </div>
      <div style="margin-top:10px;font-size:11.5px;color:#999;text-align:center;font-style:italic;">Tap any item to add to cart</div>
    </div>
  `;

  appendCard(html);
}

// ===== RENDER CART =====
// Only one live cart — removes previous cart card before showing new one
function renderCart(cartItems, total) {
  if (activeCartCardEl) {
    activeCartCardEl.remove();
    activeCartCardEl = null;
  }

  const html = `
    <div class="cart-display">
      <div class="cart-header-strip">
        <span>🛒</span>
        <span>Your Cart</span>
      </div>
      <div class="cart-items-list">
        ${cartItems.map(item => `
          <div class="cart-item-row">
            <span class="cart-item-name">${item.name.charAt(0).toUpperCase() + item.name.slice(1)}</span>
            <span class="cart-item-qty">×${item.qty}</span>
            <span class="cart-item-price">₹${(item.price * item.qty).toFixed(0)}</span>
            <button class="cart-remove-btn" onclick="removeItem('${item.name.replace(/'/g, "\\'")}')">✕</button>
          </div>
        `).join('')}
      </div>
      <div class="cart-total-row">
        <span class="cart-total-label">Total</span>
        <span class="cart-total-amount">₹${total}</span>
      </div>
      <button class="cart-confirm-btn" onclick="sendMessage('confirm order')">
        ✓ Confirm Order
      </button>
    </div>
  `;

  activeCartCardEl = appendCard(html);
}

window.removeItem = function(name) {
  sendMessage(`remove ${name}`);
};

// ===== RENDER ORDER CONFIRMED =====
function renderOrderConfirmed(orderId, items, total) {
  if (activeCartCardEl) {
    activeCartCardEl.remove();
    activeCartCardEl = null;
  }

  const html = `
    <div class="order-confirmed-card">
      <div class="order-confirmed-header">
        <span class="order-confirmed-icon">🎉</span>
        <div class="order-confirmed-title">Order Confirmed!</div>
        <div class="order-id-badge">📋 Order #${orderId}</div>
      </div>
      <div class="order-confirmed-body">
        <div class="order-items-mini">
          ${items.map(i => `
            <div class="order-item-mini-row">
              ${i.qty}× ${i.name.charAt(0).toUpperCase() + i.name.slice(1)}
            </div>
          `).join('')}
        </div>
        <div class="order-eta-strip">
          <div class="order-eta-left">⏱️ Estimated time</div>
          <div class="order-eta-time">30–40 min</div>
        </div>
        <div style="font-size:12px;color:#666;text-align:center;margin-bottom:8px;">
          💰 Total: <strong style="color:#e85d04">₹${total}</strong>
        </div>
        <div style="font-size:12px;color:#6b7280;text-align:center;margin-bottom:10px;">
          🧾 Your bill is added to the cart. Open Cart → Checkout to pay.
        </div>
        <button class="order-track-btn" onclick="sendMessage('track ${orderId}')">
          📦 Track Order #${orderId}
        </button>
      </div>
    </div>
  `;

  appendCard(html);
}

// ===== RENDER ORDER STATUS =====
const STATUS_PROGRESS = {
  pending: 10, accepted: 25, preparing: 50, ready: 70,
  out_for_delivery: 85, picked_up: 90, delivered: 100,
  completed: 100, rejected: 0, cancelled: 0
};

const STATUS_LABELS = {
  pending: 'Pending', accepted: 'Accepted', preparing: 'Preparing',
  ready: 'Ready', out_for_delivery: 'On Way', picked_up: 'Picked Up',
  delivered: 'Delivered', completed: 'Done',
  rejected: 'Rejected', cancelled: 'Cancelled'
};

function renderOrderStatus(order) {
  const status   = order.status || 'pending';
  const progress = STATUS_PROGRESS[status] || 0;
  const items    = order.items || [];
  const total    = order.total_price || order.total || 0;
  const steps    = ['Accepted', 'Preparing', 'Ready', 'Delivered'];

  const html = `
    <div class="order-status-card">
      <div class="order-status-header">
        <span class="order-status-id">Order #${order.id || order.order_id}</span>
        <span class="status-pill ${status}">${STATUS_LABELS[status] || status}</span>
      </div>
      ${!['rejected','cancelled'].includes(status) ? `
      <div class="order-progress-bar">
        <div class="progress-track">
          <div class="progress-fill" style="width: ${progress}%"></div>
        </div>
        <div class="progress-steps">
          ${steps.map(s => `
            <span class="progress-step ${
              STATUS_LABELS[status] === s || (status === 'accepted' && s === 'Accepted')
                ? 'active' : ''
            }">${s}</span>
          `).join('')}
        </div>
      </div>` : ''}
      <div class="order-status-body">
        <div style="font-size:12px;color:#666;margin-bottom:6px;font-weight:500;">Items ordered:</div>
        <div style="display:flex;flex-direction:column;gap:3px;">
          ${items.map(i => {
            // Handle both real site format (item_name/quantity) and chatbot format (name/qty)
            const qty  = i.quantity || i.qty || 1;
            const name = (i.item_name || i.name || 'Item');
            const displayName = name.charAt(0).toUpperCase() + name.slice(1);
            const price = i.price || 0;
            return `
              <div style="font-size:12.5px;color:#333;display:flex;justify-content:space-between;">
                <span>${qty}× ${displayName}</span>
                <span style="color:#e85d04;font-weight:600;">${price > 0 ? '₹' + (qty * price).toFixed(0) : ''}</span>
              </div>
            `;
          }).join('')}
        </div>
        <div style="margin-top:10px;padding-top:8px;border-top:1px solid #e8e6e1;
                    display:flex;justify-content:space-between;align-items:center;">
          <span style="font-size:11px;color:#999;text-transform:uppercase;letter-spacing:0.5px;">Total</span>
          <span style="font-size:15px;font-weight:700;color:#e85d04;">₹${total}</span>
        </div>
      </div>
    </div>
  `;

  appendCard(html);
}

// ===== QUICK ACTIONS =====
const QUICK_ACTIONS = [
  { id: "view_restaurants", label: "🍽️ View Restaurants" },
  { id: "book_table",       label: "🪑 Book a Table"     },
  { id: "help_faqs",        label: "❓ Help & FAQs"      },
  { id: "just_chat",        label: "💬 Just Chat"         }
];

function appendOptions(options) {
  const wrapper = document.createElement("div");
  wrapper.className = "message bot-msg";
  wrapper.style.flexDirection = "column";
  wrapper.style.alignItems = "flex-start";

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.style.marginBottom = "6px";
  avatar.innerHTML = `<img src="/chatbot/assets/bot-face.png" alt="DineBot">`;
  wrapper.appendChild(avatar);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.style.maxWidth = "88%";

  options.forEach(opt => {
    const b = document.createElement("button");
    b.className = "chat-option-btn";
    b.textContent = opt.label;
    b.onclick = () => handleQuickAction(opt.id);
    bubble.appendChild(b);
  });

  wrapper.appendChild(bubble);
  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
}

function handleQuickAction(actionId) {
  // Map button IDs to proper messages
  const actionMap = {
    "view_restaurants": "view restaurants",
    "book_table":       "book a table",
    "help_faqs":        "help",
    "just_chat":        "hello"
  };
  const msg = actionMap[actionId];
  if (msg) sendMessage(msg);
}

// ===== GLOBAL CLICK HANDLERS =====
window.selectRestaurant = function(id, name) {
  sendMessage(String(id));
};

window.orderItem = function(name) {
  sendMessage(`1 ${name}`);
};

// ===== PARSE RESPONSE & RENDER RICH UI =====
function handleBotResponse(data, message) {
  const reply  = data.reply  || "";
  const intent = data.intent || "";

  // ── RESTAURANTS — use JSON array from API, not text parse ──────────────────
  if (intent === "view_restaurants") {
    if (data.restaurants && data.restaurants.length > 0) {
      renderRestaurantCards(data.restaurants);
      return;
    }
    // fallback if array empty
    appendMessage("bot", reply.replace(/\*\*(.*?)\*\*/g, '$1'));
    return;
  }

  // ── RESTAURANT SELECTED ────────────────────────────────────────────────────
  if (intent === "select_restaurant") {
    appendMessage("bot", reply.replace(/\*\*(.*?)\*\*/g, '$1'));
    return;
  }

  // ── MENU ───────────────────────────────────────────────────────────────────
  if (intent === "menu" || (reply.includes("Menu:") && reply.includes("₹"))) {
    const items = [];
    reply.split('\n').forEach(line => {
      const match = line.match(/\d+\.\s+(.+?)\s+-\s+₹([\d.]+)/i);
      if (match) {
        items.push({ item_name: match[1].trim(), price: parseFloat(match[2]) });
      }
    });
    if (items.length > 0) {
      appendMessage("bot", "Here's what we're serving today 🍽️");
      renderMenuCards(items);
      return;
    }
  }

  // ── CART ───────────────────────────────────────────────────────────────────
  if (reply.includes("Added to cart") || reply.includes("Cart mein add")) {
    const cartItems  = [];
    const totalMatch = reply.match(/Total:\s*₹([\d.]+)/);
    const total      = totalMatch ? totalMatch[1] : '0';

    reply.split('\n').forEach(line => {
      const m = line.match(/•\s*(\d+)x\s+(.+?)\s+-\s+₹([\d.]+)/i);
      if (m) {
        cartItems.push({
          qty:   parseInt(m[1]),
          name:  m[2].trim(),
          price: parseFloat(m[3]) / parseInt(m[1])
        });
      }
    });

    if (cartItems.length > 0) {
      renderCart(cartItems, total);
      return;
    }
  }

  // ── ORDER CONFIRMED ────────────────────────────────────────────────────────
  if (intent === "confirm_order" &&
      (reply.includes("Order Confirmed") || reply.includes("Order Confirm Ho Gaya"))) {
    const orderIdMatch = reply.match(/Order ID:\s*\*?\*?(\d+)\*?\*?/);
    const totalMatch   = reply.match(/Total:\s*₹([\d.]+)/);
    const orderId      = orderIdMatch ? orderIdMatch[1] : '?';
    const total        = totalMatch   ? totalMatch[1]   : '0';

    const items = [];
    reply.split('\n').forEach(line => {
      const m = line.match(/•\s*(\d+)x\s+(.+)/i);
      if (m) items.push({ qty: parseInt(m[1]), name: m[2].trim() });
    });

    renderOrderConfirmed(
      orderId,
      items.length > 0 ? items : [{ qty: 1, name: 'Your order' }],
      total
    );
    return;
  }

  // ── ORDER TRACK ────────────────────────────────────────────────────────────
  if (intent === "track_order" && reply.includes("Order #")) {
    const orderIdMatch = reply.match(/Order #(\d+)/);
    const statusMatch  = reply.match(/Status:\s*\*?\*?(\w+)\*?\*?/i);
    const totalMatch   = reply.match(/Total:\s*₹([\d.]+)/);
    const orderId      = orderIdMatch ? orderIdMatch[1]          : '?';
    const status       = statusMatch  ? statusMatch[1].toLowerCase() : 'pending';

    const items = [];
    reply.split('\n').forEach(line => {
      const m = line.match(/•\s*(\d+)x\s+(.+)/i);
      if (m) items.push({ qty: parseInt(m[1]), name: m[2].trim(), price: 0 });
    });

    renderOrderStatus({
      id:          orderId,
      status:      status,
      items:       items,
      total_price: totalMatch ? totalMatch[1] : 0
    });
    return;
  }

  // ── ORDER CANCELLED ────────────────────────────────────────────────────────
  if (intent === "cancel_order" && (reply.includes("cancelled") || reply.includes("cancel ho gaya"))) {
    appendCard(`
      <div style="background:#fff1f2;border:1.5px solid #fecdd3;border-radius:12px;
                  padding:14px;text-align:center;">
        <div style="font-size:22px;margin-bottom:6px;">❌</div>
        <div style="font-size:13px;font-weight:600;color:#be123c;">Order Cancelled</div>
        <div style="font-size:12px;color:#9f1239;margin-top:4px;">
          ${reply.replace(/❌/g, '').trim()}
        </div>
      </div>
    `);
    return;
  }

  // ── DEFAULT — plain text ───────────────────────────────────────────────────
  const cleaned = reply
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1');
  appendMessage("bot", cleaned);
}

// ===== SEND MESSAGE =====
async function sendMessage(customText = null, forceAppend = false) {
  const text = String(customText ?? input.value).trim();
  const normalized = text.toLowerCase().replace(/\s+/g, " ").trim();
  const now = Date.now();
  if (!text || isSending) return;
  if (normalized && normalized === lastSubmittedMessage && now - lastSubmittedAt < 1200) return;

  lastSubmittedMessage = normalized;
  lastSubmittedAt = now;

  isSending = true;
  appendMessage("user", text);
  if (customText == null) input.value = "";
  showTyping();

  try {
    const res = await fetch("http://localhost:5000/chat", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({
        user_id: window.DINEAUS_USER_ID || "guest_" + Date.now(),
        message: text,
        is_logged_in: Boolean(window.DINEAUS_IS_LOGGED_IN),
        user_name: window.DINEAUS_USER_NAME || ""
      }),
    });

    if (!res.ok) throw new Error("Network response not OK");
    const data = await res.json();
    hideTyping();

    handleBotResponse(data, text);

    if (data.speak === true) {
      speak(data.speech_text || data.reply);
    }

  } catch (err) {
    hideTyping();
    console.error("Send error:", err);
    appendMessage("bot", "⚠️ Connection issue. Please try again.");
  } finally {
    setTimeout(() => { isSending = false; }, 300);
  }
}

// ===== SPEAK =====
function speak(text) {
  if (!text) return;
  try { window.speechSynthesis.cancel(); } catch (e) {}
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-IN";
  window.speechSynthesis.speak(u);
}

// ===== VOICE INPUT =====
let recognition = null;
let autoSend = true;
let lastTranscript = "";
let lastTime = 0;

let toggleBtn = document.getElementById("auto-toggle");
if (!toggleBtn) {
  toggleBtn = document.createElement("button");
  toggleBtn.id = "auto-toggle";
  toggleBtn.textContent = "🎙️ Auto Send ON";
  toggleBtn.className = "toggle-btn";
  const chatInputEl = document.querySelector(".chat-input") || document.body;
  chatInputEl.appendChild(toggleBtn);
}

toggleBtn.addEventListener("click", () => {
  autoSend = !autoSend;
  toggleBtn.textContent = autoSend ? "🎙️ Auto Send ON" : "🎙️ Manual Mode";
  toggleBtn.classList.toggle("off", !autoSend);
});

const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition || null;

async function ensureMicPermission() {
  if (!navigator.mediaDevices?.getUserMedia) return false;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach(t => t.stop());
    return true;
  } catch {
    alert("Please allow microphone access.");
    return false;
  }
}

async function createRecognitionInstance() {
  if (!SpeechRec) return null;
  const ok = await ensureMicPermission();
  if (!ok) return null;

  try {
    const r = new SpeechRec();
    r.lang = "en-IN";
    r.interimResults = true;
    r.continuous = true;
    r.maxAlternatives = 1;

    r.onstart = () => {
      micBtn.textContent = "🎙️";
      micBtn.classList.add("listening");
      micBtn.style.backgroundColor = "#ff4444";
    };
    r.onend = () => {
      micBtn.textContent = "🎤";
      micBtn.classList.remove("listening");
      micBtn.style.backgroundColor = "";
    };
    r.onresult = (e) => {
      try {
        const resultIndex = e.results.length - 1;
        const transcript  = String(e.results[resultIndex][0].transcript || "").trim();
        if (!transcript) return;
        const now = Date.now();
        if (transcript.toLowerCase() === lastTranscript.toLowerCase() && now - lastTime < 1500) return;
        lastTranscript = transcript;
        lastTime = now;
        if (autoSend) {
          setTimeout(() => sendMessage(transcript, true), 600);
        } else {
          input.value = transcript;
        }
        recognition.stop();
      } catch (err) { console.error("Recognition result error:", err); }
    };
    r.onerror = (err) => {
      micBtn.style.backgroundColor = "";
      if (err?.error === "not-allowed") alert("❌ Microphone access denied!");
      micBtn.textContent = "🎤";
      micBtn.classList.remove("listening");
    };
    return r;
  } catch { return null; }
}

if (!SpeechRec) {
  micBtn.addEventListener("click", () => {
    alert("❌ Speech not supported. Please use Chrome or Edge.");
  });
} else {
  micBtn.addEventListener("click", async () => {
    if (!recognition) {
      recognition = await createRecognitionInstance();
      if (!recognition) return;
    }
    try { recognition.abort(); } catch (e) {}
    recognition.start();
  });
}

// ===== TOGGLE CHAT =====
chatToggle.addEventListener("click", () => {
  setChatbotOpen(!chatContainer.classList.contains("open"));
});

minimizeBtn.addEventListener("click", () => {
  setChatbotOpen(false);
});

resetBtn.addEventListener("click", async () => {
  hideTyping();
  activeCartCardEl = null;
  messages.innerHTML = "";
  appendMessage("bot", "Hi 👋 I'm DineBot. How can I help you today?");
  appendOptions(QUICK_ACTIONS);

  // Reset Python session too
  try {
    await fetch("http://localhost:5000/reset", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ user_id: window.DINEAUS_USER_ID || "guest" })
    });
  } catch (e) {
    console.log("Session reset skipped:", e);
  }
});

// ===== INPUT EVENTS =====
btn.addEventListener("click", () => sendMessage());
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    sendMessage();
  }
});

// ===== INIT =====
window.addEventListener("DOMContentLoaded", () => {
  setChatbotOpen(false);
  appendMessage("bot", "Hi 👋 I'm DineBot. Welcome!");
  appendOptions(QUICK_ACTIONS);
});

// ===== TYPING INDICATOR =====
let typingBubble = null;

function showTyping() {
  if (typingBubble) return;
  typingBubble = document.createElement("div");
  typingBubble.className = "message bot-msg";
  typingBubble.innerHTML = `
    <div class="avatar"><img src="/chatbot/assets/bot-face.png" alt="DineBot"></div>
    <div class="bubble typing">
      <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    </div>
  `;
  messages.appendChild(typingBubble);
  messages.scrollTop = messages.scrollHeight;
}

function hideTyping() {
  if (typingBubble) {
    typingBubble.remove();
    typingBubble = null;
  }
}
