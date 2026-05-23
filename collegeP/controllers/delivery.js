const connection = require("../config/db");
const ExpressError = require("../utils/ExpressError");
const bcrypt = require("bcrypt");


exports.register = async (req, res, next) => {
  const { name, phone, vehicle, email, password } = req.body;

  if (!name || !phone || !email || !password) {
    req.flash("error", "Please fill all required fields");
    return res.redirect("back");
  }

  const hashedPassword = await bcrypt.hash(password, 10);

  const sql = `
    INSERT INTO delivery_partner (name, phone, vehicle, email, password)
    VALUES (?, ?, ?, ?, ?)
  `;

  connection.query(
    sql,
    [name, phone, vehicle, email, hashedPassword],
    (err) => {
      if (err) {
        return next(new ExpressError(500, "Failed to register delivery partner"));
      }

      req.flash("success", "Registration successful. Please login");
      res.redirect("/delivery/login");
    }
  );
};

// LOGIN
exports.renderLogin = (req, res) => {
    res.render("delivery/delivery-login.ejs");
};

exports.login = (req, res, next) => {
  const { email, password } = req.body;

  if (!email || !password) {
    req.flash("error", "Please enter email and password");
    return res.redirect("/delivery/login");
  }

  connection.query(
    "SELECT * FROM delivery_partner WHERE email = ?",
    [email],
    async (err, rows) => {
      if (err) {
        return next(new ExpressError(500, "Database error"));
      }

      if (!rows.length) {
        req.flash("error", "Invalid credentials");
        return res.redirect("/delivery/login");
      }

      const delivery_partner = rows[0];
      const match = await bcrypt.compare(password, delivery_partner.password);

      if (!match) {
        req.flash("error", "Invalid credentials");
        return res.redirect("/delivery/login");
      }

      req.session.deliveryPartner = delivery_partner;

      res.redirect(`/delivery/dashboard/${delivery_partner.id}`);
    }
  );
};



// DASHBOARD (assigned orders)
exports.dashboard = (req, res) => {
  res.render("delivery/delivery-dashboard.ejs", {
    partner: req.session.deliveryPartner
  });
};

// exports.order = (req, res, next) => {
//   const partner = req.session.deliveryPartner;

//   if (partner.id != req.params.id) {
//     return next(new ExpressError(403, "Unauthorized access"));
//   }

//   const readyQ = `
//     SELECT * FROM orders
//     WHERE status = 'ready'
//     AND delivery_partner_id IS NULL
//   `;

//   const myQ = `
//     SELECT * FROM orders
//     WHERE delivery_partner_id = ?
//     ORDER BY created_at DESC
//   `;

//   connection.query(readyQ, (err, readyOrders) => {
//     if (err) return next(new ExpressError(500, "Failed to load ready orders"));

//     readyOrders.forEach(o => {
//       try {
//         o.items = typeof o.items === "string" ? JSON.parse(o.items) : o.items;
//       } catch {
//         o.items = [];
//       }
//     });

//     connection.query(myQ, [partner.id], (err2, myOrders) => {
//       if (err2) return next(new ExpressError(500, "Failed to load your orders"));

//       myOrders.forEach(o => {
//         try {
//           o.items = typeof o.items === "string" ? JSON.parse(o.items) : o.items;
//         } catch {
//           o.items = [];
//         }
//       });

//       const allOrders = [
//         ...readyOrders.map(o => ({ ...o, _type: "ready" })),
//         ...myOrders.map(o => ({ ...o, _type: "mine" }))
//       ];
      
//       res.render("delivery/delivery-orders.ejs", {
//         partner,
//         orders: allOrders
//       });
      
//     });
//   });
// };

exports.order = (req, res, next) => {
  const partner = req.session.deliveryPartner;

  if (partner.id != req.params.id) {
    return next(new ExpressError(403, "Unauthorized access"));
  }

  const readyQ = `
    SELECT 
      o.*,
      r.name AS restaurant_name,
      r.address AS restaurant_address,
      r.ownerNumber AS restaurant_phone,
      u.firstname AS user_name,
      u.number AS user_phone
    FROM orders o
    JOIN restaurant r ON o.restaurant_id = r.id
    JOIN one u ON o.user_id = u.id
    WHERE o.status = 'ready'
      AND o.delivery_partner_id IS NULL
  `;

  const myQ = `
    SELECT 
      o.*,
      r.name AS restaurant_name,
      r.address AS restaurant_address,
      r.ownerNumber AS restaurant_phone,
      u.firstname AS user_name,
      u.number AS user_phone
    FROM orders o
    JOIN restaurant r ON o.restaurant_id = r.id
    JOIN one u ON o.user_id = u.id
    WHERE o.delivery_partner_id = ?
  `;

  connection.query(readyQ, (err, readyOrders) => {
    if (err) return next(new ExpressError(500, "Failed to load ready orders"));

    readyOrders.forEach(o => {
      try {
        o.items = typeof o.items === "string" ? JSON.parse(o.items) : o.items;
      } catch {
        o.items = [];
      }
    });

    connection.query(myQ, [partner.id], (err2, myOrders) => {
      if (err2) return next(new ExpressError(500, "Failed to load your orders"));

      myOrders.forEach(o => {
        try {
          o.items = typeof o.items === "string" ? JSON.parse(o.items) : o.items;
        } catch {
          o.items = [];
        }
      });

      const allOrders = [
        ...readyOrders.map(o => ({ ...o, _type: "ready" })),
        ...myOrders.map(o => ({ ...o, _type: "mine" }))
      ];

      res.render("delivery/delivery-orders.ejs", {
        partner,
        orders: allOrders
      });
    });
  });
};


// exports.acceptOrder = (req, res, next) => {
//   const partnerId = req.session.deliveryPartner.id;
//   const orderId = req.params.id;

//   const sql = `
//     UPDATE orders
//     SET delivery_partner_id = ?
//     WHERE id = ? AND status = 'ready' AND delivery_partner_id IS NULL
//   `;

//   connection.query(sql, [partnerId, orderId], (err, result) => {
//     if (err) {
//       return next(new ExpressError(500, "Failed to accept order"));
//     }

//     if (result.affectedRows === 0) {
//       return next(new ExpressError(409, "Order already taken"));
//     }

//     res.redirect("/delivery/orders/" + partnerId);
//   });
// };
exports.acceptOrder = (req, res, next) => {
  const partner = req.session.deliveryPartner;
  const orderId = req.params.id;
  const io = req.app.get("io");

  const sql = `
    UPDATE orders
    SET delivery_partner_id = ?
    WHERE id = ? AND status = 'ready' AND delivery_partner_id IS NULL
  `;

  connection.query(sql, [partner.id, orderId], (err, result) => {
    if (err) return next(new ExpressError(500, "Failed to accept order"));
    if (result.affectedRows === 0)
      return next(new ExpressError(409, "Order already taken"));

    // 🔥 get restaurant id and emit
    connection.query(
      "SELECT restaurant_id FROM orders WHERE id = ?",
      [orderId],
      (err2, rows) => {
        if (!err2 && rows.length) {
          const restaurantId = rows[0].restaurant_id;

          io.to("restaurant_" + restaurantId).emit("deliveryAssigned", {
            orderId,
            name: partner.name,
            phone: partner.phone
          });
        }
      }
    );

    res.redirect("/delivery/orders/" + partner.id);
  });
};

// function updateDeliveryStatus(req, res, next, status, timeColumn) {
//   const io = req.app.get("io");
//   const orderId = req.params.id;
//   const partnerId = req.session.deliveryPartner.id;

//   const sql = `
//     UPDATE orders
//     SET status = ?, ${timeColumn} = NOW()
//     WHERE id = ? AND delivery_partner_id = ?
//   `;

//   connection.query(sql, [status, orderId, partnerId], (err, result) => {
//     if (err) {
//       return next(new ExpressError(500, "Failed to update order status"));
//     }

//     if (result.affectedRows === 0) {
//       return next(new ExpressError(403, "Order not assigned to you"));
//     }

//     io.to("order_" + orderId).emit("orderStatusUpdate", {
//       orderId,
//       status,
//       timestamp: new Date().toISOString()
//     });

//     res.redirect("/delivery/orders/" + partnerId);
//   });
// }

// function updateDeliveryStatus(req, res, next, status, timeColumn) {
//   const io = req.app.get("io");
//   const orderId = req.params.id;
//   const partnerId = req.session.deliveryPartner.id;

//   const sql = `
//     UPDATE orders
//     SET status = ?, ${timeColumn} = NOW()
//     WHERE id = ? AND delivery_partner_id = ?
//   `;

//   connection.query(sql, [status, orderId, partnerId], (err, result) => {
//     if (err) {
//       return next(new ExpressError(500, "Failed to update order status"));
//     }

//     if (result.affectedRows === 0) {
//       return next(new ExpressError(403, "Order not assigned to you"));
//     }

//     // ✅ TRACK ORDER PAGE UPDATE
//     io.to("order_" + orderId).emit("orderStatusUpdate", {
//       orderId,
//       status,
//       timestamp: new Date().toISOString()
//     });
//     io.to("restaurant_" + req.session.deliveryPartner.restaurant_id).emit("orderStatusUpdate", {
//       orderId,
//       status
//     });
    
//     // ✅ notify restaurant panel also
//     connection.query(
//       "SELECT restaurant_id FROM orders WHERE id = ?",
//       [orderId],
//       (e2, r2) => {
//         if (r2 && r2.length) {
//           const restaurantId = r2[0].restaurant_id;
    
//           io.to("restaurant_" + restaurantId).emit("deliveryStatusUpdate", {
//             orderId,
//             status
//           });
//         }
//       }
//     );
    

//     // ✅ PROFILE PAGE REALTIME UPDATE
//     connection.query(
//       "SELECT user_id FROM orders WHERE id = ?",
//       [orderId],
//       (e, rows) => {
//         if (rows && rows.length) {
//           const userId = rows[0].user_id;

//           io.to("user_" + userId).emit("profileOrderUpdate", {
//             orderId,
//             status
//           });
//         }
//       }
//     );

//     res.redirect("/delivery/orders/" + partnerId);
//   });
// }

function updateDeliveryStatus(req, res, next, status, timeColumn) {
  const io = req.app.get("io");
  const orderId = req.params.id;
  const partnerId = req.session.deliveryPartner.id;

  const sql = `
    UPDATE orders
    SET status = ?, ${timeColumn} = NOW()
    WHERE id = ? AND delivery_partner_id = ?
  `;

  connection.query(sql, [status, orderId, partnerId], (err, result) => {
    if (err) return next(new ExpressError(500, "Failed to update order status"));
    if (result.affectedRows === 0)
      return next(new ExpressError(403, "Order not assigned to you"));

    // get restaurant + user
    connection.query(
      "SELECT restaurant_id, user_id FROM orders WHERE id = ?",
      [orderId],
      (e, rows) => {
        if (rows && rows.length) {
          const { restaurant_id, user_id } = rows[0];

          // ✅ customer track page
          io.to("order_" + orderId).emit("orderStatusUpdate", { orderId, status });

          // ✅ restaurant dashboard
          io.to("restaurant_" + restaurant_id).emit("orderStatusUpdate", {
            orderId,
            status
          });

          // ✅ profile page
          io.to("user_" + user_id).emit("profileOrderUpdate", { orderId, status });
        }
      }
    );

    res.redirect("/delivery/orders/" + partnerId);
  });
}

exports.pickupOrder = (req, res, next) =>
  updateDeliveryStatus(req, res, next, "picked_up", "picked_up_at");

exports.outForDelivery = (req, res, next) =>
  updateDeliveryStatus(req, res, next, "out_for_delivery", "out_for_delivery_at");

exports.delivered = (req, res, next) =>
  updateDeliveryStatus(req, res, next, "delivered", "delivered_at");


