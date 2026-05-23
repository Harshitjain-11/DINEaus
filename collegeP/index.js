const express = require("express");
const app = express();
const { spawn } = require("child_process");
const connection = require("./config/db");
const path = require("path");

const methodOverride = require("method-override");
// const ExpressError = require("./utils/ExpressError");
const session = require("express-session");
const flash = require("connect-flash");

const http = require("http");
const { Server } = require("socket.io"); 
const server = http.createServer(app);
const io = new Server(server);

const pythonPath = path.join(__dirname, "../foodin-chatbot/venv/Scripts/python.exe");
const pythonApp  = path.join(__dirname, "../foodin-chatbot/app.py");
const pythonProcess = spawn(pythonPath, [pythonApp], { stdio: "inherit" });

pythonProcess.on("close", (code) => {
  console.log(`❌ Python chatbot stopped: ${code}`);
});

process.on("exit", () => pythonProcess.kill());

app.set("io", io);
io.on("connection", (socket) => {
  console.log("User connected:", socket.id);

  socket.on("joinOrderRoom", (orderId) => {
    socket.join("order_" + orderId);
    console.log("User joined room:", "order_" + orderId);
  });
  socket.on("joinRestaurantRoom", (restaurantId) => {
  socket.join("restaurant_" + restaurantId); 
  console.log("Admin/Client joined restaurant room:", "restaurant_" + restaurantId);
  });
  // ✅ DELIVERY BOY LIVE LOCATION UPDATE (NEW - SAFE ADDITION)
  // ✅ BOOKING ROOM JOIN (VERY IMPORTANT)
  socket.on("joinBookingRoom", bookingId => {
    socket.join("booking_" + bookingId);
    console.log("User joined booking room:", bookingId);
  });
    socket.on("joinUserRoom", (userId) => {
    socket.join("user_" + userId);
    console.log("User joined personal room:", "user_" + userId);
  });
  
  socket.on("delivery:locationUpdate", ({ orderId, lat, lng }) => {
    if (!orderId || !lat || !lng) return;
  
    // ✅ DB me last known location save karo
    connection.query(
      `UPDATE orders 
       SET delivery_lat = ?, delivery_lng = ?, delivery_last_update = NOW()
       WHERE id = ?`,
      [lat, lng, orderId]
    );
  
    // ✅ Customer ko real-time location bhejo
    io.to("order_" + orderId).emit("order:deliveryLocation", {
      orderId,
      lat,
      lng,
      updatedAt: new Date().toISOString()
    });
    
  });


});


app.use(express.json());
app.use(express.urlencoded({ extended: true }));
app.set("view engine", "ejs");
app.set("views", path.join(__dirname, "/views"));
app.use(methodOverride("_method"));
app.use(express.static(path.join(__dirname, "public")));
const { uiNavigationGuard } = require("./middlewares");






app.use(session({
    secret: "secretKey",
    resave: false,
    saveUninitialized: true
}));
app.use(flash());
app.use(uiNavigationGuard);

app.use((req, res, next) => {
  res.locals.success = req.flash("success");
  res.locals.error = req.flash("error");
  next();
});
// Middleware: Make session user available in all EJS views
app.use((req, res, next) => {
  res.locals.user = req.session.user || null;
  res.locals.addresses = req.session.addresses || [];   // ✅ ADD
  next();
});





const userRoutes = require("./routes/user");
const restaurantRoutes = require("./routes/restaurant");
const deliveryRoutes = require("./routes/delivery");
const adminRoutes = require("./routes/admin");

app.use("/", userRoutes);
app.use("/", restaurantRoutes);
app.use("/", deliveryRoutes);
app.use("/", adminRoutes);
const runScheduledOrders = require("./cron/scheduledOrders");
runScheduledOrders(io);

const ExpressError = require("./utils/ExpressError");

app.use((err, req, res, next) => {
  const { statusCode = 500, message = "Something went wrong" } = err;

  console.error("🔥 ERROR:", err);

  res.status(statusCode).render("error.ejs", { message });
});
// ❌ 404 handler (must be last)
app.use((req, res) => {
  res.status(404).render("404");
});

  

server.listen(8080,"0.0.0.0", () => {
  console.log("Server running on port 8080");
});
