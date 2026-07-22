<p align="center">
  <img src="https://img.shields.io/badge/Node.js-339933?style=for-the-badge&logo=nodedotjs&logoColor=white" />
  <img src="https://img.shields.io/badge/Express-000000?style=for-the-badge&logo=express&logoColor=white" />
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
  <img src="https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white" />
  <img src="https://img.shields.io/badge/MySQL-4479A1?style=for-the-badge&logo=mysql&logoColor=white" />
  <img src="https://img.shields.io/badge/Socket.IO-010101?style=for-the-badge&logo=socketdotio&logoColor=white" />
  <img src="https://img.shields.io/badge/scikit--learn-F7931E?style=for-the-badge&logo=scikitlearn&logoColor=white" />
  <img src="https://img.shields.io/badge/EJS-B4CA65?style=for-the-badge&logo=ejs&logoColor=black" />
</p>

# 🍽️ DINEaus — AI-Powered Food Ordering & Table Reservation Platform

> A production-grade, full-stack food delivery platform with an **AI chatbot** that supports **natural language ordering**, **real-time order tracking**, and **multi-role dashboards** — built using a **polyglot microservice architecture** (Node.js + Python).

---

## 📋 Table of Contents

- [Highlights](#-highlights)
- [System Architecture](#-system-architecture)
- [Tech Stack](#-tech-stack)
- [Key Features](#-key-features)
- [AI Chatbot — Deep Dive](#-ai-chatbot--deep-dive)
- [Database Design](#-database-design)
- [Real-Time Communication](#-real-time-communication)
- [Project Structure](#-project-structure)
- [Getting Started](#-getting-started)
- [API Endpoints](#-api-endpoints)
- [Security Measures](#-security-measures)
- [Screenshots](#-screenshots)
- [Future Roadmap](#-future-roadmap)

---

## 🏆 Highlights

| Metric | Value |
|--------|-------|
| **Architecture** | Multi-server polyglot (Node.js + Python) |
| **Total Codebase** | ~5,000+ lines across 40+ files |
| **AI/ML** | TF-IDF + Logistic Regression intent classifier with Groq LLM fallback |
| **Real-Time** | Socket.IO — live order tracking, instant notifications |
| **Roles** | 4 dashboards — Customer, Restaurant Admin, Delivery Partner, Platform Admin |
| **Database** | 10+ relational tables with foreign keys, JSON fields, ENUM constraints |
| **NLP** | Bilingual support — English + Hinglish (Hindi-English) |

---

## 🏗️ System Architecture

```
                        ┌──────────────────────────┐
                        │     USER'S BROWSER        │
                        │  (EJS Pages + Chatbot JS) │
                        └─────┬──────────┬──────────┘
                              │          │
                    HTTP/Socket.IO    HTTP (fetch)
                    Port 8080         Port 5000
                              │          │
                 ┌────────────▼──┐   ┌───▼──────────────┐
                 │  Node.js       │   │  Python Flask     │
                 │  Express       │   │  Chatbot Server   │
                 │                │   │                   │
                 │ • Routes/Auth  │   │ • NLP/ML Engine   │
                 │ • Order Mgmt   │   │ • Intent Predict  │
                 │ • EJS Render   │   │ • Entity Extract  │
                 │ • Socket.IO    │   │ • Groq LLM        │
                 │ • Cron Jobs    │   │ • Session Mgmt    │
                 └───────┬───────┘   └────────┬──────────┘
                         │    child_process     │
                         │    spawn()           │
                         │  (Node starts Python)│
                         │                      │
                         └──────────┬───────────┘
                                    │
                          ┌─────────▼─────────┐
                          │   MySQL (3306)     │
                          │ DB: college_practice│
                          │ 10+ tables         │
                          │ Shared by both     │
                          └────────────────────┘
```

### How the Two Servers Communicate

> **Key Insight:** Node.js and Python do **not** communicate directly. The **browser acts as the intermediary.**

1. **Node.js (port 8080)** serves the web pages (EJS templates) including the chatbot widget
2. **Chatbot JavaScript** in the browser sends `fetch()` requests **directly** to **Python (port 5000)**
3. **Python** processes the NLP request and responds with JSON **back to the browser**
4. **CORS** is configured on Flask to allow cross-origin requests from port 8080

```js
// Browser → Python (public/chatbot/script.js)
const res = await fetch("http://localhost:5000/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ user_id, message, is_logged_in, user_name })
});
```

### Server Boot Sequence

Node.js automatically spawns the Python server as a child process:

```js
// index.js — Lines 18-26
const pythonProcess = spawn(pythonPath, [pythonApp], { stdio: "inherit" });

process.on("exit", () => pythonProcess.kill()); // Cleanup on exit
```

---

## 🛠️ Tech Stack

### Backend
| Technology | Role |
|-----------|------|
| **Node.js + Express** | Main application server — routing, auth, sessions, order processing |
| **Python + Flask** | AI chatbot microservice — NLP, intent prediction, entity extraction |
| **MySQL** | Relational database — 10+ tables with foreign keys and constraints |
| **Socket.IO** | Real-time bidirectional communication (WebSockets) |

### Frontend
| Technology | Role |
|-----------|------|
| **EJS (Embedded JavaScript)** | Server-side rendered templates (31 view files) |
| **Vanilla JS** | Client-side interactivity, chatbot widget, AJAX |
| **CSS** | Custom role-based stylesheets |

### AI / ML
| Technology | Role |
|-----------|------|
| **scikit-learn** | TF-IDF Vectorizer + Logistic Regression pipeline for intent classification |
| **spaCy** | Named Entity Recognition (NER) for noun chunks and POS tagging |
| **Groq API (Llama 3.1 8B)** | LLM fallback for unrecognized queries |
| **Regex + difflib** | Entity extraction (order IDs, quantities, dates, times) + fuzzy matching |

### DevOps & Tools
| Technology | Role |
|-----------|------|
| **node-cron** | Scheduled order activation (checks every minute) |
| **bcrypt** | Password hashing (salt rounds: 10) |
| **multer** | File upload handling (menu images) |
| **express-session** | Server-side session management |
| **nodemailer** | Email notifications |

---

## ✨ Key Features

### 👤 Customer Portal
- **Browse Restaurants** — with cuisine filters, search, and Swiggy-style image cards
- **Menu & Cart** — add items, manage quantities, guest cart → DB cart merge on login
- **Order Placement** — instant or scheduled orders with address selection
- **Real-Time Order Tracking** — live status updates via Socket.IO with timeline view
- **Table Reservation** — date/time/seat selection with pre-ordering capability
- **AI Chatbot** — natural language ordering, booking, tracking via conversational UI
- **Profile Dashboard** — order history, booking history, address management, reorder
- **Password Recovery** — captcha-verified reset token flow
- **Voice Input** — speech-to-text chatbot input using Web Speech API

### 🍕 Restaurant Admin Dashboard
- **Partner Registration** — multi-step restaurant onboarding with document upload
- **Live Order Feed** — real-time new order notifications via Socket.IO
- **Order Lifecycle** — accept → preparing → ready → completed (with timestamps)
- **Booking Management** — accept/reject reservations, mark arrived/completed
- **Menu Management** — add/edit items with image upload (multer + OCR support)

### 🚗 Delivery Partner Portal
- **Registration & Login** — dedicated auth for delivery partners
- **Order Assignment** — view available orders, accept deliveries
- **Live Location Sharing** — GPS coordinates broadcast via Socket.IO
- **Status Updates** — picked up → out for delivery → delivered

### 👑 Platform Admin
- **Restaurant Approval** — approve/reject new restaurant applications
- **Platform Statistics** — overview dashboard
- **System Management** — centralized control panel

---

## 🤖 AI Chatbot — Deep Dive

### Architecture

```
User Message: "I want 2 burgers"
         │
         ▼
┌─────────────────────────────────────────────┐
│              app.py (Brain)                  │
│                                              │
│  1. Language Detection (Hindi/English)        │
│         │                                    │
│  2. Intent Prediction (ML Model)             │
│     ├── confidence ≥ 0.35 → Use prediction   │
│     └── confidence < 0.35 → Groq LLM fallback│
│         │                                    │
│  3. Entity Extraction                        │
│     ├── Items: [{name:"burger", qty:2}]      │
│     ├── Order IDs, dates, times              │
│     └── Booking: people, time, date          │
│         │                                    │
│  4. Session State Update                     │
│     └── Track conversation context           │
│         │                                    │
│  5. Response Generation                      │
│     └── Bilingual (EN/HI) responses          │
└─────────────────────────────────────────────┘
```

### ML Pipeline

```python
# train_chatbot.py
model = make_pipeline(
    TfidfVectorizer(ngram_range=(1, 2), stop_words="english"),
    LogisticRegression(max_iter=2000)
)
# Trained on intents.json → Saved as chatbot_model.pkl
```

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Vectorizer** | TF-IDF (1,2)-gram | Converts text → numerical feature vectors |
| **Classifier** | Logistic Regression | Classifies vectors → intent labels |
| **Threshold** | 0.35 confidence | Below threshold → Groq LLM fallback |
| **Entity Extraction** | spaCy + Regex | Extracts quantities, items, dates, times |
| **Fuzzy Matching** | difflib | Matches misspelled items to menu (e.g., "burgr" → "burger") |

### Supported Intents

| Intent | Example Input | Action |
|--------|--------------|--------|
| `greeting` | "Hello", "Namaste" | Welcome message |
| `view_restaurants` | "Show restaurants" | List restaurant cards |
| `menu` | "Show menu" | Display menu items |
| `order` | "I want 2 burgers" | Add to cart |
| `confirm_order` | "Place my order" | Insert into DB |
| `track_order` | "Track order 42" | Show order status |
| `cancel_order` | "Cancel order 42" | Cancel if eligible |
| `book_table` | "Book table for 4 tomorrow 7pm" | Create reservation |
| `help` | "How to order?" | Show instructions |
| `fallback` | Unknown query | Groq LLM response |

### Bilingual Support (English + Hinglish)

```python
# Language detection via Hindi marker words
_HINDI_MARKERS = {'kya','hai','mujhe','chahiye','karo','kal','aaj','baje',...}

# Entity extraction handles Hinglish
# "4 log" → 4 people    |  "kal" → tomorrow's date
# "7 baje" → 19:00      |  "do burger" → 2 burgers
```

---

## 🗄️ Database Design

### Entity-Relationship Overview

```
┌──────────┐     ┌────────────┐     ┌───────────┐
│  one     │────<│ cart_items  │>────│ menu_item │
│ (users)  │     └────────────┘     └─────┬─────┘
│          │                              │
│          │──<── orders ──>──── restaurant│
│          │                              │
│          │──<── reservations ──>─────────┘
│          │
│          │──<── address
└──────────┘

restaurant ──<── restaurant_admin
restaurant ──<── restaurant_seats
reservations ──<── reservation_preorders ──>── menu_item
orders ──>── delivery_partner
```

### Tables (10+)

| Table | Purpose | Key Fields |
|-------|---------|-----------|
| `one` | Users | id, email (UNIQUE), password (bcrypt), reset_token |
| `restaurant` | Restaurants | status (ENUM: pending/approved/rejected), lat/lng |
| `menu_item` | Menu items | price, vegNonveg, cuisine, is_available |
| `cart_items` | Shopping cart | user_id (FK), item_id (FK), quantity |
| `orders` | Orders | items (JSON), status (11-state ENUM), scheduled_for |
| `address` | Delivery addresses | lat/lng, FK → one(id) ON DELETE CASCADE |
| `reservations` | Table bookings | status (6-state ENUM), seat_id, time_slot |
| `restaurant_seats` | Seat inventory | seat_type, is_available |
| `reservation_preorders` | Pre-orders for bookings | FK → reservations, menu_item |
| `restaurant_admin` | Restaurant admins | role (owner/manager/staff) |
| `delivery_partner` | Delivery partners | name, phone, vehicle |
| `platform_admin` | Super admins | Platform-level access |

### Order Status State Machine

```
scheduled → pending → accepted → preparing → ready → picked_up → out_for_delivery → delivered/completed
              ↓          ↓
           rejected   cancelled
```

---

## ⚡ Real-Time Communication

### Socket.IO Rooms

| Room Pattern | Who Joins | Events |
|-------------|-----------|--------|
| `restaurant_{id}` | Restaurant admin | `newOrder`, `bookingStatusUpdate` |
| `order_{id}` | Customer tracking order | `order:deliveryLocation` |
| `booking_{id}` | Customer with booking | `bookingStatusUpdate` |
| `user_{id}` | Logged-in user | `profileOrderUpdate` |

### Real-Time Features

```js
// Live delivery tracking (index.js)
socket.on("delivery:locationUpdate", ({ orderId, lat, lng }) => {
  // Save to DB
  connection.query(`UPDATE orders SET delivery_lat=?, delivery_lng=? WHERE id=?`);
  // Broadcast to customer
  io.to("order_" + orderId).emit("order:deliveryLocation", { lat, lng });
});
```

- **Instant Order Notifications** — restaurant sees new orders without refresh
- **Live Order Status** — customer sees status changes in real-time
- **Delivery GPS Tracking** — live lat/lng updates on map
- **Booking Updates** — real-time accept/reject notifications

---

## 📁 Project Structure

```
DINEaus/
│
├── collegeP/                      # 🟢 Node.js Main Server (Port 8080)
│   ├── index.js                   # ⭐ Entry point — Express, Socket.IO, Python spawn
│   ├── config/
│   │   └── db.js                  # MySQL connection (Singleton)
│   ├── routes/
│   │   ├── user.js                # 27 user routes
│   │   ├── restaurant.js          # Restaurant admin routes
│   │   ├── delivery.js            # Delivery partner routes
│   │   └── admin.js               # Platform admin routes
│   ├── controllers/
│   │   ├── user.js                # User logic (1689 lines)
│   │   ├── restaurant.js          # Restaurant logic
│   │   ├── delivery.js            # Delivery logic
│   │   └── admin.js               # Admin logic
│   ├── views/                     # EJS templates (31 files)
│   │   ├── user/                  # 16 customer pages
│   │   ├── restaurant/            # 9 restaurant admin pages
│   │   ├── delivery/              # 4 delivery pages
│   │   ├── admin/                 # 2 platform admin pages
│   │   └── includes/              # Reusable: navbar, flash messages
│   ├── middlewares.js             # Auth guards (5 middleware functions)
│   ├── utils/
│   │   ├── ExpressError.js        # Custom error class
│   │   ├── wrapAsync.js           # Async error wrapper
│   │   └── multer.js              # File upload config
│   ├── cron/
│   │   └── scheduledOrders.js     # Cron: activate scheduled orders
│   ├── schemas/                   # SQL table definitions
│   └── public/                    # Static assets
│       ├── chatbot/               # Chatbot frontend (script.js, style.css)
│       ├── css/                   # Role-based stylesheets
│       ├── js/                    # Role-based frontend JS
│       └── uploads/               # User-uploaded images
│
├── foodin-chatbot/                # 🐍 Python Chatbot Server (Port 5000)
│   ├── app.py                     # ⭐ Flask server — 2567 lines, all chat logic
│   ├── order_manager.py           # MySQL queries for chatbot operations
│   ├── train_chatbot.py           # ML model training script
│   ├── chatbot/
│   │   ├── model_loader.py        # Load trained .pkl model
│   │   ├── intent_predictor.py    # Predict intent from text
│   │   ├── entity_extractor.py    # Extract items, dates, quantities
│   │   ├── response_generator.py  # Pick response from intents.json
│   │   └── session_manager.py     # Track conversation state per user
│   └── data/
│       ├── intents.json           # Training data (patterns + responses)
│       ├── chatbot_model.pkl      # Trained ML model
│       └── groq_system_prompt.txt # LLM system prompt (13KB)
│
└── README.md
```

---

## 🚀 Getting Started

### Prerequisites

- **Node.js** ≥ 18.x
- **Python** ≥ 3.9
- **MySQL** ≥ 8.0
- **npm** and **pip**

### 1. Clone the Repository

```bash
git clone https://github.com/Harshitjain-11/DINEaus.git
cd DINEaus
```

### 2. Setup MySQL Database

```sql
CREATE DATABASE college_practice;
USE college_practice;

-- Run all schemas
SOURCE schemas/schema.sql;
SOURCE schemas/schema3.sql;
SOURCE schemas/schema4.sql;
SOURCE schemas/schema5.sql;
SOURCE schemas/schema6.sql;
```

### 3. Setup Node.js Server

```bash
cd collegeP
npm install
```

### 4. Setup Python Chatbot

```bash
cd foodin-chatbot
python -m venv venv
venv\Scripts\activate         # Windows
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 5. Configure Environment

Create `foodin-chatbot/.env`:
```env
DB_USER=root
DB_PASS=your_password
DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=college_practice
FLASK_DEBUG=1
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=llama-3.1-8b-instant
```

### 6. Train the ML Model (first time)

```bash
cd foodin-chatbot
python train_chatbot.py
# ✅ Improved model trained and saved successfully!
```

### 7. Start the Application

```bash
cd collegeP
npx nodemon index.js
# ✅ DB connected!
# ✅ MySQL connection established (Python)
# 🚀 DineBot Server Starting... Port: 5000
# 🚀 Server running on port 8080
```

> Node.js automatically spawns the Python server — no need to start it separately.

Open: **http://localhost:8080/home**

---

## 🔌 API Endpoints

### Node.js Express (Port 8080)

<details>
<summary><b>User Routes (27 endpoints)</b></summary>

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/home` | — | Home page with restaurants |
| GET | `/login` | — | Login page |
| POST | `/login` | — | Authenticate user |
| GET | `/sign` | — | Signup page |
| POST | `/sign` | — | Create account |
| GET | `/restaurant/:id` | — | Restaurant page + menu |
| GET | `/cart/checkout` | — | Cart page (add via `?item_id=`) |
| POST | `/cart/update` | — | Update cart quantity |
| GET | `/payment` | ✅ | Payment page |
| GET | `/payment/success` | ✅ | Place order + notify restaurant |
| GET | `/profile` | ✅ | User profile + order history |
| GET | `/track-order/:id` | ✅ | Live order tracking |
| GET | `/search` | — | Search page |
| GET | `/search-ajax` | — | AJAX search results |
| GET | `/reserve/:id` | ✅ | Table booking form |
| POST | `/reservation/create-full` | ✅ | Create reservation |
| POST | `/order/:id/cancel` | ✅ | Cancel scheduled order |
| POST | `/booking/:id/cancel` | ✅ | Cancel booking |

</details>

<details>
<summary><b>Restaurant Admin Routes</b></summary>

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/restaurant-admin/order/:id/accept` | Accept incoming order |
| POST | `/restaurant-admin/order/:id/preparing` | Mark as preparing |
| POST | `/restaurant-admin/order/:id/ready` | Mark as ready |
| POST | `/restaurant-admin/order/:id/completed` | Mark as completed |
| POST | `/restaurant-admin/booking/:id/accept` | Accept reservation |
| POST | `/restaurant-admin/booking/:id/arrived` | Mark guest arrived |

</details>

### Python Flask (Port 5000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/chat` | Send message, get chatbot response |
| POST | `/reset` | Reset chat session |
| GET | `/health` | Health check (ML model, DB status) |

---

## 🔒 Security Measures

| Measure | Implementation |
|---------|---------------|
| **Password Hashing** | bcrypt with 10 salt rounds |
| **SQL Injection Prevention** | Parameterized queries (`?` in Node, `%s` in Python) |
| **XSS Prevention** | HTML escaping in chatbot (`escapeHtml()` function) |
| **Session Security** | Server-side sessions with express-session |
| **CORS Configuration** | Flask-CORS restricts cross-origin access |
| **Auth Middleware** | 5 role-based guards (isLoggedIn, isRestaurantAdmin, etc.) |
| **UI Navigation Guard** | Prevents direct URL access to restricted pages |
| **Input Validation** | Server-side validation on all forms |
| **Password Reset** | Time-limited tokens (15 min expiry) |

---

## 🗺️ Future Roadmap

- [ ] **JWT Authentication** — replace sessions for stateless auth
- [ ] **MySQL Connection Pool** — replace single connection for better concurrency
- [ ] **Payment Gateway** — Razorpay/Stripe integration
- [ ] **Docker Compose** — containerize both servers
- [ ] **Redis Session Store** — persist sessions across restarts
- [ ] **Deep Learning NLP** — upgrade from Logistic Regression to transformer model
- [ ] **React Frontend** — migrate from EJS to React SPA
- [ ] **CI/CD Pipeline** — GitHub Actions for automated testing
- [ ] **Rate Limiting** — protect chatbot API from spam
- [ ] **PWA Support** — installable progressive web app

---

## 👨‍💻 Author

**Harshit Jain** — [GitHub](https://github.com/Harshitjain-11)

---

## 📄 License

This project is licensed under the ISC License.
