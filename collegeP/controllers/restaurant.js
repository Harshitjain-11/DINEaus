const connection = require("../config/db");
const bcrypt = require("bcrypt");
const Tesseract = require("tesseract.js");
const ExpressError = require("../utils/ExpressError");

exports.addRestaurant = (req, res, next) => {
  const {ownerName,name,Address,email,ownerNumber,location,image_url} = req.body;

  const query = `
    INSERT INTO restaurant 
    (ownerName, name, Address, email, ownerNumber, location, image_url)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `;

  connection.query(
    query,
    [ownerName, name, Address, email, ownerNumber, location, image_url],
    (err) => {
      if (err) {
        console.error("❌ Restaurant onboarding error:", err);
        return next(new ExpressError(500, "Failed to register restaurant"));
      }

      req.flash(
        "success",
        "Restaurant registered successfully. Our team will contact you soon."
      );
      res.redirect("/resturant-document");
    }
  );
};

exports.uploadMenu = async (req, res, next) => {
  const { costfortwo, vegNonveg, cuisine, restaurantName } = req.body;

  if (!req.file) {
    req.flash("error", "Please upload a menu image");
    return res.redirect("back");
  }

  const filePath = req.file.path;
  const filename = req.file.filename;

  try {
    const result = await Tesseract.recognize(filePath, "eng", {
      logger: m => console.log(m),
    });

    const text = result.data.text;
    const lines = text
      .split("\n")
      .map(l => l.trim())
      .filter(l => l.length > 0);

    connection.query(
      "SELECT id FROM restaurant WHERE name = ?",
      [restaurantName],
      (err, rows) => {
        if (err) {
          return next(new ExpressError(500, "Database error"));
        }

        if (!rows.length) {
          return next(new ExpressError(404, "Restaurant not found"));
        }

        const restaurantId = rows[0].id;

        lines.forEach(line => {
          let match =
            line.match(/(.+?)\s*[-–=:]?\s*(₹|\$|Rs\.?)\s*(\d+(\.\d+)?)/i) ||
            line.match(/(.+?)\s*[-–=:]?\s*(\d{2,5})/);

          if (!match) return;

          const name = match[1].trim().replace(/[^\w\s]/gi, "").trim();
          let price = match[3] || match[2];

          if (!price.includes(".") && parseInt(price) > 1000) {
            price = (parseInt(price) / 100).toFixed(2);
          }

          connection.query(
            `INSERT INTO menu_item
             (restaurant_id, item_name, price, costfortwo, vegNonveg, cuisine, menu_image, common_image)
             VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
            [
              restaurantId,
              name,
              price,
              costfortwo,
              vegNonveg,
              cuisine,
              filename,
              null
            ],
            err => {
              if (err) {
                console.error("Menu insert error:", err);
              }
            }
          );
        });

        req.flash("success", "Menu uploaded and processed successfully");
        res.redirect("/resturant-menu");
      }
    );
  } catch (err) {
    console.error("Tesseract error:", err);
    return next(new ExpressError(500, "Failed to process menu image"));
  }
};

exports.adminLogin = (req, res, next) => {
  const { email, password } = req.body;

  if (!email || !password) {
    req.flash("error", "Please enter email and password");
    return res.redirect("/restaurant-admin/login");
  }

  connection.query(
    "SELECT * FROM restaurant_admin WHERE email = ?",
    [email],
    async (err, rows) => {
      if (err) {
        return next(new ExpressError(500, "Database error during login"));
      }

      if (!rows.length) {
        req.flash("error", "Admin not found");
        return res.redirect("/restaurant-admin/login");
      }

      const admin = rows[0];
      const match = await bcrypt.compare(password, admin.password);

      if (!match) {
        req.flash("error", "Incorrect password");
        return res.redirect("/restaurant-admin/login");
      }

      req.session.restaurantAdmin = {
        id: admin.id,
        restaurant_id: admin.restaurant_id,
        email: admin.email,
        role: admin.role
      };

      res.redirect("/restaurant-admin/dashboard");
    }
  );
};

// exports.dashboard = (req, res, next) => {
//   const restaurantId = req.session.restaurantAdmin.restaurant_id;

//   const sql = `
//     SELECT * FROM orders 
//     WHERE restaurant_id = ? 
//     ORDER BY created_at DESC
//   `;

//   connection.query(sql, [restaurantId], (err, orders) => {
//     if (err) {
//       return next(new ExpressError(500, "Failed to load orders"));
//     }

//     res.render("restaurant/restaurant-admin-dashboard", {
//       pending: orders.filter(o => o.status === "pending"),
//       accepted: orders.filter(o => o.status === "accepted"),
//       preparing: orders.filter(o => o.status === "preparing"),
//       ready: orders.filter(o => o.status === "ready"),
//       completed: orders.filter(o => o.status === "completed"),
//     });
//   });
// };
exports.dashboard = (req, res, next) => {
  const restaurantId = req.session.restaurantAdmin.restaurant_id;

  const orderQuery = 
  `SELECT 
  o.*,
  d.name AS delivery_name,
  d.phone AS delivery_phone
FROM orders o
LEFT JOIN delivery_partner d ON o.delivery_partner_id = d.id
WHERE o.restaurant_id = ?
ORDER BY o.created_at DESC
`

  connection.query(orderQuery, [restaurantId], (err, orders) => {
    if (err) {
      return next(new ExpressError(500, "Failed to load orders"));
    }

    // ✅ order sections
    const pending = orders.filter(o => o.status === "pending");
    const accepted = orders.filter(o => o.status === "accepted");
    const preparing = orders.filter(o => o.status === "preparing");
    // const ready = orders.filter(o => o.status === "ready");
    
    // 👇 READY COLUMN ME DELIVERY KE STATUS BHI DIKHENGE
     const ready = orders.filter(o =>
       ["ready", "picked_up", "out_for_delivery", "delivered"].includes(o.status)
     );
    const completed = orders.filter(o => o.status === "completed");

    // ✅ now fetch reservations
    const reservationQuery = `
      SELECT 
        r.*,
        rp.item_id,
        rp.quantity,
        m.item_name,
        m.price
      FROM reservations r
      LEFT JOIN reservation_preorders rp ON r.id = rp.reservation_id
      LEFT JOIN menu_item m ON rp.item_id = m.id
      WHERE r.restaurant_id = ?
      ORDER BY 
      r.date DESC,
      r.time_slot DESC,
      r.created_at DESC
    
    `;
    
    connection.query(reservationQuery, [restaurantId], (err2, rows) => {
      if (err2) return next(new ExpressError(500, "Failed to load reservations"));
    
      const reservationMap = {};
    
      rows.forEach(r => {
        if (!reservationMap[r.id]) {
          reservationMap[r.id] = {
            id: r.id,
            customer_name: r.customer_name,
            customer_phone: r.customer_phone,
            date: r.date,
            time_slot: r.time_slot,
            guests: r.guests,
            status: r.status, 
            created_at: r.created_at,
            preorders: []
          };
        }
    
        if (r.item_id) {
          reservationMap[r.id].preorders.push({
            item_name: r.item_name,
            price: r.price,
            quantity: r.quantity
          });
        }
      });
    
      const reservations = Object.values(reservationMap);
        reservations.sort((a, b) => {
        return new Date(b.created_at) - new Date(a.created_at);
      });
      
      const activeReservations = reservations.filter(r =>
        ["pending", "accepted", "arrived"].includes(r.status)
      );
      
      // ✅ HISTORY = jo complete ho chuki ya cancel/reject
      const historyReservations = reservations.filter(r =>
        ["completed", "rejected", "cancelled"].includes(r.status)
      );
      
      res.render("restaurant/restaurant-admin-dashboard", {
        pending,
        accepted,
        preparing,
        ready,
        completed,
        activeReservations,
        historyReservations,
        restaurantId: req.session.restaurant_id 
      });
    });
    
  });
};

function updateOrderStatus(req, res, next, status, timeColumn = null, emitToUser = true) {
  const io = req.app.get("io");
  const orderId = req.params.id;
  const userId = req.session.user.id;
  const restaurantId = req.session.restaurantAdmin.restaurant_id;

  let query = "UPDATE orders SET status = ?";
  const params = [status];

  if (timeColumn) {
    query += `, ${timeColumn} = NOW()`;
  }

  query += " WHERE id = ? AND restaurant_id = ?";
  params.push(orderId, restaurantId);

  connection.query(query, params, (err, result) => {
    if (err) {
      return next(new ExpressError(500, "Failed to update order status"));
    }

    if (result.affectedRows === 0) {
      return next(new ExpressError(404, "Order not found"));
    }

    if (emitToUser) {
      io.to("order_" + orderId).emit("orderStatusUpdate", {
        orderId,
        status,
        timestamp: new Date().toISOString()
      });
      io.to("user_" + userId).emit("profileOrderUpdate", {
        orderId,
        status
      });
      
    }

    res.redirect("/restaurant-admin/dashboard");
  });
}
exports.rejectOrder = (req, res, next) =>
  updateOrderStatus(req, res, next, "rejected", null, false);

exports.acceptOrder = (req, res, next) =>
  updateOrderStatus(req, res, next, "accepted", "accepted_at");

exports.preparingOrder = (req, res, next) =>
  updateOrderStatus(req, res, next, "preparing", "preparing_at");

exports.readyOrder = (req, res, next) =>
  updateOrderStatus(req, res, next, "ready", "ready_at");

exports.completedOrder = (req, res, next) => {
  const io = req.app.get("io");
  const orderId = req.params.id;
  const restaurantId = req.session.restaurantAdmin.restaurant_id;

  const sql = `
    UPDATE orders 
    SET status = 'completed'
    WHERE id = ? 
      AND restaurant_id = ? 
      AND status = 'delivered'
  `;

  connection.query(sql, [orderId, restaurantId], (err, result) => {
    if (err) {
      return next(new ExpressError(500, "Failed to complete order"));
    }

    if (result.affectedRows === 0) {
      req.flash("error", "Order not delivered yet. Cannot complete.");
      return res.redirect("/restaurant-admin/dashboard");
    }

    // ✅ optional: notify user profile also
    connection.query(
      "SELECT user_id FROM orders WHERE id = ?",
      [orderId],
      (e, r) => {
        if (r && r.length) {
          io.to("user_" + r[0].user_id).emit("profileOrderUpdate", {
            orderId,
            status: "completed"
          });
        }
      }
    );

    req.flash("success", "Order completed successfully");
    res.redirect("/restaurant-admin/dashboard");
  });
};


exports.orderHistory = (req, res, next) => {
  const restaurantId = req.session.restaurantAdmin.restaurant_id;

  const sql = `
    SELECT * FROM orders 
    WHERE restaurant_id = ? 
    AND status IN ('completed', 'rejected')
    ORDER BY created_at DESC
  `;

  connection.query(sql, [restaurantId], (err, history) => {
    if (err) {
      return next(new ExpressError(500, "Failed to load order history"));
    }

    res.render("restaurant/restaurant-order-history", { history });
  });
};
exports.acceptBooking = (req, res) => {
  const { id } = req.params;
  const io = req.app.get("io");
  connection.query(
    "UPDATE reservations SET status='accepted' WHERE id=? AND status='pending'",
    [id],
    (err) => {
      if (err) {
        req.flash("error", "Failed to accept booking");
        return res.redirect("/restaurant-admin/dashboard");
      }
      io.to("booking_" + id).emit("bookingStatusUpdate", {
        bookingId: id,
        status: "accepted"
      });
      req.flash("success", "Booking accepted");
      res.redirect("/restaurant-admin/dashboard");
    }
  );
};


exports.rejectBooking = (req, res) => {
  const { id } = req.params;
  const io = req.app.get("io");
  connection.query(
    "UPDATE reservations SET status='rejected' WHERE id=?AND status='pending'",
    [id],
    (err) => {
      if (err) {
        req.flash("error", "Failed to reject booking");
        return res.redirect("/restaurant-admin/dashboard");
      }
      io.to("booking_" + id).emit("bookingStatusUpdate", {
        bookingId: id,
        status: "rejected"
      });
      req.flash("success", "Booking rejected");
      res.redirect("/restaurant-admin/dashboard");
    }
  );
};
exports.markBookingArrived = (req, res) => {
  const { id } = req.params;
  const io = req.app.get("io");
  connection.query(
    "UPDATE reservations SET status='arrived' WHERE id=?AND status='accepted'",
    [id],
    (err) => {
      if (err) {
        req.flash("error", "Failed to update arrival");
        return res.redirect("/restaurant-admin/dashboard");
      }
      io.to("booking_" + id).emit("bookingStatusUpdate", {
        bookingId: id,
        status: "arrived"
      });
      req.flash("success", "Guest marked as arrived");
      res.redirect("/restaurant-admin/dashboard");
    }
  );
};

exports.markBookingCompleted = (req, res) => {
  const { id } = req.params;
  const io = req.app.get("io");
  connection.query(
    "UPDATE reservations SET status='completed' WHERE id=?AND status='arrived'",
    [id],
    (err) => {
      if (err) {
        req.flash("error", "Failed to complete booking");
        return res.redirect("/restaurant-admin/dashboard");
      }
      io.to("booking_" + id).emit("bookingStatusUpdate", {
        bookingId: id,
        status: "completed"
      });
      req.flash("success", "Booking completed");
      res.redirect("/restaurant-admin/dashboard");
    }
  );
};
