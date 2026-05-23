const connection = require("../config/db");
const getCommonImageName = require("../utils/getCommonImageName");
const bcrypt = require("bcrypt");
const ExpressError = require("../utils/ExpressError");

// GET: login page
exports.renderLogin = (req, res) => {
  res.render("user/login");
};


exports.login = async (req, res, next) => {
  const { email, password } = req.body;

  connection.query(
    "SELECT * FROM one WHERE email = ?",
    [email],
    async (err, rows) => {
      if (err) return next(new ExpressError(500, "DB error"));
      if (!rows.length) {
        req.flash("error", "Invalid email or password");
        return res.redirect("/login");
      }

      const dbUser = rows[0];
      const match = await bcrypt.compare(password, dbUser.password);

      if (!match) {
        req.flash("error", "Invalid email or password");
        return res.redirect("/login");
      }

      // ✅ Session user
      req.session.user = {
        id: dbUser.id,
        firstname: dbUser.firstname,
        email: dbUser.email,
        role: "USER"
      };

      const restaurantId = req.session.restaurant_id;

      // ✅ Merge guest cart → DB cart
      if (
        restaurantId &&
        Array.isArray(req.session.guestCart) &&
        req.session.guestCart.length > 0
      ) {
        req.session.guestCart.forEach(item => {
          const check =
            "SELECT id FROM cart_items WHERE user_id = ? AND item_id = ?";

          connection.query(check, [dbUser.id, item.item_id], (err2, rows2) => {
            if (err2) return console.error("Cart migrate error", err2);

            if (rows2.length) {
              connection.query(
                "UPDATE cart_items SET quantity = quantity + ? WHERE id = ?",
                [item.quantity, rows2[0].id]
              );
            } else {
              connection.query(
                "INSERT INTO cart_items (user_id, restaurant_id, item_id, quantity) VALUES (?, ?, ?, ?)",
                [dbUser.id, restaurantId, item.item_id, item.quantity]
              );
            }
          });
        });

        // ✅ clear guest cart
        req.session.guestCart = [];
      }

      // ✅ Fetch all user's addresses after login
      connection.query(
        "SELECT * FROM address WHERE user_id = ? ORDER BY id DESC",
        [dbUser.id],
        (addrErr, addrRows) => {
          if (addrErr) {
            console.error("Address fetch error:", addrErr);
            req.session.addresses = [];
          } else {
            req.session.addresses = addrRows || [];
          }
      
          return res.redirect("/home");
        }
      );
      
    }
  );
};

// GET: signup page
exports.renderSignup = (req, res) => {
  res.render("user/sign");
};

// POST: signup logic
exports.signup = async (req, res, next) => {
  const { firstname, lastname, email, number, password, confirm } = req.body;

  // 🔴 User validation error
  if (password !== confirm) {
    req.flash("error", "Passwords do not match");
    return res.redirect("/signup");
  }

  let hashedPassword;
  try {
    hashedPassword = await bcrypt.hash(password, 10);
  } catch (err) {
    return next(new ExpressError(500, "Error securing password"));
  }

  connection.query(
    `INSERT INTO one (firstname, lastname, email, number, password)
     VALUES (?, ?, ?, ?, ?)`,
    [firstname, lastname, email, number, hashedPassword],
    (err) => {

      // 🔴 Duplicate email (user error)
      if (err && err.code === "ER_DUP_ENTRY") {
        req.flash("error", "Email already registered");
        return res.redirect("/signup");
      }

      // 🔴 Other DB errors (system error)
      if (err) {
        return next(new ExpressError(500, "Database error during signup"));
      }

      // ✅ SUCCESS
      req.flash("success", "Account created successfully. Please login.");
      res.redirect("/login");
    }
  );
};

exports.logout = (req, res) => {
  req.session.guestCart = [];   // 👈 guest cart reset
  req.session.destroy(() => {
    res.redirect("/home");
  });
};
exports.renderHome = (req, res, next) => {
  const user = req.session.user || null;

  const restaurantQuery = `
    SELECT r.*, GROUP_CONCAT(DISTINCT m.cuisine SEPARATOR ', ') AS cuisines
    FROM restaurant r
    LEFT JOIN menu_item m ON r.id = m.restaurant_id
    WHERE r.status = 'approved'
    GROUP BY r.id
  `;

  // 👉 Guest user
  if (!user) {
    return connection.query(restaurantQuery, (err, restaurants) => {
      if (err) {
        return next(
          new ExpressError(500, "Database error while fetching restaurants")
        );
      }

      return res.render("user/home.ejs", {
        user: null,
        restaurants
      });
    });
  }

  // 👉 Logged-in user
  const userQuery =
    "SELECT id, firstname, lastname, email FROM one WHERE id = ?";

  connection.query(userQuery, [user.id], (err, userResult) => {
    if (err) {
      return next(new ExpressError(500, "Database error while fetching user"));
    }

    if (!userResult.length) {
      req.session.destroy(() => {
        req.flash("error", "Session expired. Please login again");
        res.redirect("/login");
      });
      return;
    }

    const safeUser = userResult[0];

    connection.query(restaurantQuery, (err2, restaurants) => {
      if (err2) {
        return next(
          new ExpressError(500, "Database error while fetching restaurants")
        );
      }

      res.render("user/home.ejs", {
        user: safeUser,
        restaurants
      });
    });
  });
};

exports.showRestaurant = (req, res, next) => {
  const restaurantId = req.params.id;
  const user = req.session.user || null;

  const restaurantQuery = `
    SELECT r.*, GROUP_CONCAT(DISTINCT m.cuisine) AS cuisines
    FROM restaurant r
    LEFT JOIN menu_item m ON r.id = m.restaurant_id
    WHERE r.id = ?
    GROUP BY r.id
  `;

  const menuQuery = `
    SELECT id, item_name, price, costfortwo, vegNonveg, cuisine, menu_image, common_image
    FROM menu_item
    WHERE restaurant_id = ?
  `;

  connection.query(restaurantQuery, [restaurantId], (err, results) => {
    if (err) {
      return next(new ExpressError(500, "Failed to load restaurant"));
    }

    if (!results.length) {
      return next(new ExpressError(404, "Restaurant not found"));
    }

    const restaurant = results[0];

    connection.query(menuQuery, [restaurantId], (err2, menuItems) => {
      if (err2) {
        return next(new ExpressError(500, "Failed to load menu"));
      }

      // ✅ cart ke liye context
      req.session.restaurant_id = restaurant.id;

      res.render("user/resturant-card.ejs", {
        restaurant,
        menuItems,
        getCommonImageName
      });
    });
  });
};
exports.renderReservationForm = (req, res, next) => {
  const restaurantId = req.params.id;
  const userId = req.session.user.id;

  const restaurantQuery = "SELECT * FROM restaurant WHERE id = ?";
  const menuQuery = "SELECT * FROM menu_item WHERE restaurant_id = ?";
  const seatsQuery = "SELECT * FROM restaurant_seats WHERE restaurant_id = ?";
  const userQuery = `
    SELECT id, firstname, lastname, email, number
    FROM one
    WHERE id = ?
  `;

  // 1️⃣ Restaurant
  connection.query(restaurantQuery, [restaurantId], (err, rest) => {
    if (err) {
      return next(new ExpressError(500, "Failed to load restaurant"));
    }
    if (!rest.length) {
      return next(new ExpressError(404, "Restaurant not found"));
    }

    const restaurant = rest[0];

    // 2️⃣ Menu
    connection.query(menuQuery, [restaurantId], (err2, menuItems) => {
      if (err2) {
        return next(new ExpressError(500, "Failed to load menu"));
      }

      // 3️⃣ Seats
      connection.query(seatsQuery, [restaurantId], (err3, seats) => {
        if (err3) {
          return next(new ExpressError(500, "Failed to load seats"));
        }

        // 4️⃣ User (SESSION → ID)
        connection.query(userQuery, [userId], (err4, users) => {
          if (err4) {
            return next(new ExpressError(500, "Failed to load user"));
          }

          if (!users.length) {
            req.session.destroy(() => {
              req.flash("error", "Session expired. Please login again");
              res.redirect("/login");
            });
            return;
          }

          const user = users[0];

          // 🔐 keep restaurant context
          req.session.restaurant_id = restaurant.id;

          res.render("user/reservation-form.ejs", {
            restaurant,
            menuItems,
            seats,
            user,
            getCommonImageName
          });
        });
      });
    });
  });
};


exports.getRestaurantSeats = (req, res) => {
  const { restaurant_id } = req.query;

  if (!restaurant_id) {
    return res.json([]);
  }

  connection.query(
    "SELECT * FROM restaurant_seats WHERE restaurant_id = ?",
    [restaurant_id],
    (err, rows) => {
      if (err) return res.json([]);
      res.json(rows);
    }
  );
};

exports.getReservationSlots = (req, res) => {
  const { restaurant_id, date } = req.query;

  if (!restaurant_id || !date) {
    return res.json([]);
  }

  connection.query(
    `
    SELECT time_slot, COUNT(*) AS total 
    FROM reservations 
    WHERE restaurant_id = ? AND date = ?
    GROUP BY time_slot
    `,
    [restaurant_id, date],
    (err, result) => {
      if (err) return res.json([]);

      const out = result.map(r => ({
        slot: r.time_slot,
        available: r.total < 5
      }));

      res.json(out);
    }
  );
};

exports.createReservation = (req, res, next) => {

  if (!req.session.user) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }

  const userId = req.session.user.id;

  const {
    restaurant_id,
    name,
    phone,
    date,
    time_slot,
    guests,
    seat_id,
    preorder
  } = req.body;

  console.log("RESERVATION BODY 👉", req.body); // ✅ debug

  if (!restaurant_id || !date || !time_slot) {
    req.flash("error", "Invalid reservation data");
    return res.redirect("back");
  }
  // ✅ DATE VALIDATION: only today to next 3 days allowed

const bookingDate = new Date(date);
bookingDate.setHours(0,0,0,0);

const today = new Date();
today.setHours(0,0,0,0);

const maxDate = new Date();
maxDate.setDate(today.getDate() + 3);
maxDate.setHours(0,0,0,0);

if (bookingDate < today || bookingDate > maxDate) {
  req.flash("error", "You can only book within next 3 days");
  return res.redirect("back");
}


  connection.query(
    `
    INSERT INTO reservations
    (restaurant_id, customer_name, customer_phone, date, time_slot, guests, seat_id, user_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `,
    [restaurant_id, name, phone, date, time_slot, guests, seat_id || null, userId],
    (err, result) => {
      if (err) {
        console.error("RESERVATION ERROR:", err);
        return next(new ExpressError(500, "Failed to create reservation"));
      }

      const reservation_id = result.insertId;
      const io = req.app.get("io");

      // 🔥 realtime push to restaurant for new booking
      io.to("restaurant_" + restaurant_id).emit("newBooking", {
        id: reservation_id,
        restaurant_id,
        date,
        time_slot,
        guests,
        status: "pending"
      });

      // 🥘 preorder
      if (preorder && typeof preorder === "object") {
        Object.entries(preorder).forEach(([itemId, qty]) => {
          if (qty > 0) {
            connection.query(
              `
              INSERT INTO reservation_preorders (reservation_id, item_id, quantity)
              VALUES (?, ?, ?)
              `,
              [reservation_id, itemId, qty]
            );
          }
        });
      }

      // 🪑 seat lock
      if (seat_id) {
        connection.query(
          "UPDATE restaurant_seats SET is_available = 0 WHERE id = ?",
          [seat_id]
        );
      }

      req.flash("success", "Reservation successful");
      res.redirect(`/restaurant/${restaurant_id}`);
    }
  );
};



exports.renderSearch = (req, res) => {
  res.render("user/navbar-search", {
    query: "",
    restaurants: []
  });
};

exports.searchAjax = (req, res) => {
  const searchQuery = req.query.q ? req.query.q.trim() : "";

  if (!searchQuery) {
    return res.json([]);
  }

  // 🔍 Restaurant search
  const sqlRestaurants = `
    SELECT id, name, image_url
    FROM restaurant
    WHERE name LIKE ?
  `;

  connection.query(sqlRestaurants, [`%${searchQuery}%`], (err, restaurants) => {
    if (err) {
      console.error("Restaurant search error:", err);
      return res.json([]);
    }

    // 🔍 Dish search
    const sqlDishes = `
      SELECT 
        menu_item.id,
        menu_item.item_name,
        menu_item.price,
        menu_item.restaurant_id,
        restaurant.name AS restaurant_name,
        restaurant.image_url AS restaurant_image
      FROM menu_item
      JOIN restaurant ON menu_item.restaurant_id = restaurant.id
      WHERE menu_item.item_name LIKE ?
    `;

    connection.query(sqlDishes, [`%${searchQuery}%`], (err2, dishes) => {
      if (err2) {
        console.error("Dish search error:", err2);
        return res.json([]);
      }

      // ❌ no user info
      const restaurantsOut = restaurants.map(r => ({
        ...r,
        type: "restaurant"
      }));

      const dishesOut = dishes.map(d => ({
        ...d,
        type: "dish"
      }));

      res.json([...restaurantsOut, ...dishesOut]);
    });
  });
};

exports.renderCart = (req, res, next) => {
  const user = req.session.user || null;
  const restaurantId = req.session.restaurant_id;
  const itemId = req.query.item_id;
  // Guest cart init
  if (!Array.isArray(req.session.guestCart)) {
    req.session.guestCart = [];
  }

  /* ---------------- ADD ITEM ---------------- */
  if (itemId) {
    // 👉 Guest user
    if (!user) {
      const existing = req.session.guestCart.find(
        i => String(i.item_id) === String(itemId)
      );

      if (existing) {
        existing.quantity += 1;
      } else {
        req.session.guestCart.push({
          item_id: itemId,
          quantity: 1
        });
      }
      return loadCart();
    }

    // 👉 Logged in user
    const checkQuery =
      "SELECT id FROM cart_items WHERE user_id = ? AND item_id = ?";

    connection.query(checkQuery, [user.id, itemId], (err, rows) => {
      if (err) return next(new ExpressError(500, "Cart error"));

      if (rows.length) {
        connection.query(
          "UPDATE cart_items SET quantity = quantity + 1 WHERE id = ?",
          [rows[0].id]
        );
      } else {
        connection.query(
          "INSERT INTO cart_items (user_id, restaurant_id, item_id, quantity) VALUES (?, ?, ?, 1)",
          [user.id, restaurantId, itemId]
        );
      }

      loadCart();
    });
  } else {
    loadCart();
  }

  /* ---------------- LOAD CART ---------------- */
  function loadCart() {
    const resolvedRestaurantId = () => {
      if (restaurantId) return Promise.resolve(restaurantId);
      if (user) {
        return new Promise((resolve, reject) => {
          connection.query(
            "SELECT restaurant_id FROM cart_items WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            [user.id],
            (err, rows) => {
              if (err) return reject(err);
              resolve(rows?.[0]?.restaurant_id || null);
            }
          );
        });
      }
      if (itemId) {
        return new Promise((resolve, reject) => {
          connection.query(
            "SELECT restaurant_id FROM menu_item WHERE id = ?",
            [itemId],
            (err, rows) => {
              if (err) return reject(err);
              resolve(rows?.[0]?.restaurant_id || null);
            }
          );
        });
      }
      if (req.session.guestCart.length > 0) {
        const firstId = req.session.guestCart[0].item_id;
        return new Promise((resolve, reject) => {
          connection.query(
            "SELECT restaurant_id FROM menu_item WHERE id = ?",
            [firstId],
            (err, rows) => {
              if (err) return reject(err);
              resolve(rows?.[0]?.restaurant_id || null);
            }
          );
        });
      }
      return Promise.resolve(null);
    };

    resolvedRestaurantId()
      .then((restId) => {
        if (!restId) return null;
        return new Promise((resolve, reject) => {
          connection.query(
            "SELECT * FROM restaurant WHERE id = ?",
            [restId],
            (err, restRows) => {
              if (err) return reject(err);
              resolve(restRows?.[0] || null);
            }
          );
        });
      })
      .then((restaurant) => {

      // ======================
      // 👤 GUEST CART
      // ======================
      if (!user) {

        if (req.session.guestCart.length === 0) {
          return res.render("user/cart", {
            user: null,
            restaurant,
            addresses: [],
            menuItems: [],   // 👈 empty cart UI
            isEmpty: true
          });
        }

        const itemIds = req.session.guestCart.map(i => i.item_id);

        const guestQuery = `
          SELECT id, item_name, price, menu_image
          FROM menu_item
          WHERE id IN (?)
        `;

        connection.query(guestQuery, [itemIds], (err2, dbItems) => {
          if (err2) return next(new ExpressError(500, "Guest cart error"));

          const merged = dbItems.map(db => {
            const s = req.session.guestCart.find(
              i => String(i.item_id) === String(db.id)
            );
            return {
              ...db,
              quantity: s?.quantity || 1
            };
          });

          return res.render("user/cart", {
            user: null,
            restaurant,
            addresses: [],
            menuItems: merged,
            isEmpty: false
          });
        });

        return;
      }

      // ======================
      // 🔐 LOGGED IN CART
      // ======================
      const cartQuery = `
        SELECT m.*, c.quantity
        FROM cart_items c
        JOIN menu_item m ON c.item_id = m.id
        WHERE c.user_id = ? AND c.restaurant_id = ?
      `;

      const addressQuery = "SELECT * FROM address WHERE user_id = ?";

      connection.query(cartQuery, [user.id, restaurantId || restaurant?.id], (err3, cartItems) => {
        if (err3) return next(new ExpressError(500, "Cart load failed"));

        connection.query(addressQuery, [user.id], (err4, addresses) => {
          if (err4) return next(new ExpressError(500, "Address load failed"));

          return res.render("user/cart", {
            user,
            restaurant,
            addresses,
            menuItems: cartItems,
            isEmpty: cartItems.length === 0
          });
        });
      });
    })
    .catch((err) => next(new ExpressError(500, "Cart load failed")));
  }
};

exports.updateCart = (req, res, next) => {
  const { item_id, action } = req.body;
  const user = req.session.user || null;

  if (!Array.isArray(req.session.guestCart)) {
    req.session.guestCart = [];
  }

  /* ---------- GUEST CART ---------- */
  if (!user) {
    const item = req.session.guestCart.find(
      i => String(i.item_id) === String(item_id)
    );

    if (!item) return res.redirect("/cart/checkout");

    if (action === "increase") item.quantity++;
    else item.quantity--;

    if (item.quantity <= 0) {
      req.session.guestCart = req.session.guestCart.filter(
        i => String(i.item_id) !== String(item_id)
      );
    }

    return res.redirect("/cart/checkout");
  }

  /* ---------- LOGGED IN CART ---------- */
  const updateQuery =
    action === "increase"
      ? "UPDATE cart_items SET quantity = quantity + 1 WHERE user_id = ? AND item_id = ?"
      : "UPDATE cart_items SET quantity = quantity - 1 WHERE user_id = ? AND item_id = ?";

  connection.query(updateQuery, [user.id, item_id], (err) => {
    if (err) return next(new ExpressError(500, "Cart update failed"));

    connection.query(
      "DELETE FROM cart_items WHERE user_id = ? AND item_id = ? AND quantity <= 0",
      [user.id, item_id],
      () => res.redirect("/cart/checkout")
    );
  });
};

exports.deleteAddress = (req, res, next) => {
  if (!req.session.user) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }

  const { address_id } = req.body;
  const userId = req.session.user.id;

  if (!address_id) {
    req.flash("error", "Invalid address");
    return res.redirect("/cart/checkout");
  }

  const deleteQuery =
    "DELETE FROM address WHERE id = ? AND user_id = ?";

  connection.query(deleteQuery, [address_id, userId], (err, result) => {
    if (err) {
      return next(new ExpressError(500, "Failed to delete address"));
    }

    if (result.affectedRows === 0) {
      req.flash("error", "Address not found");
      return res.redirect("/cart/checkout");
    }

    // ✅ Reload remaining addresses
    connection.query(
      "SELECT * FROM address WHERE user_id = ? ORDER BY id DESC",
      [userId],
      (err2, rows) => {
        if (!err2) {
          req.session.addresses = rows || [];
        }
    
        req.flash("success", "Address deleted successfully");
        res.redirect("/cart/checkout");
      }
    );
    
  });
};


exports.renderPayment = (req, res, next) => {
  if (!req.session.user || !req.session.restaurant_id) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }

  const userId = req.session.user.id;
  const restaurantId = req.session.restaurant_id;

  const restaurantQuery = "SELECT * FROM restaurant WHERE id = ?";
  const addressQuery = "SELECT * FROM address WHERE user_id = ? LIMIT 1";

  // 1️⃣ Restaurant
  connection.query(restaurantQuery, [restaurantId], (err1, restResult) => {
    if (err1) {
      return next(new ExpressError(500, "Failed to load restaurant"));
    }

    if (!restResult.length) {
      return next(new ExpressError(404, "Restaurant not found"));
    }

    const restaurant = restResult[0];

    // 2️⃣ Address
    connection.query(addressQuery, [userId], (err2, addressResult) => {
      if (err2) {
        return next(new ExpressError(500, "Failed to load address"));
      }

      if (!addressResult.length) {
        req.flash("error", "Please add a delivery address first");
        return res.redirect("/cart/checkout");
      }

      const address = addressResult[0];

      res.render("user/payment.ejs", {
        user: req.session.user,   // light session user
        restaurant,
        address
      });
    });
  });
};

exports.renderProfile = (req, res, next) => {
  if (!req.session.user) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }

  const userId = req.session.user.id;

  const userQuery = `
    SELECT id, firstname, lastname, email, number
    FROM one
    WHERE id = ?
  `;

  const ordersQuery = `
    SELECT 
      o.id,
      o.restaurant_id, 
      o.total_price,
      o.status,
      o.created_at,
      r.name AS restaurant_name,
      o.scheduled_for,
      r.image_url
    FROM orders o
    JOIN restaurant r ON o.restaurant_id = r.id
    WHERE o.user_id = ?
    ORDER BY o.created_at DESC
  `;
  const bookingsQuery = `
    SELECT
      r.id,
      r.date,
      r.time_slot,
      r.guests,
      r.status,
      r.created_at,
      res.name AS restaurant_name,
      rp.item_id,
      rp.quantity,
      m.item_name
    FROM reservations r
    JOIN restaurant res ON r.restaurant_id = res.id
    LEFT JOIN reservation_preorders rp ON r.id = rp.reservation_id
    LEFT JOIN menu_item m ON rp.item_id = m.id
    WHERE r.user_id = ?
    ORDER BY r.created_at DESC
  `;

  

  connection.query(userQuery, [userId], (err1, users) => {
    if (err1) {
      return next(new ExpressError(500, "Failed to load user profile"));
    }

    if (!users.length) {
      return next(new ExpressError(404, "User not found"));
    }

    const user = users[0];

    connection.query(ordersQuery, [userId], (err2, orders) => {
      if (err2) {
        return next(new ExpressError(500, "Failed to load orders"));
      }
    // ✅ CANCEL LOGIC FOR SCHEDULED ORDERS
const now = new Date();

orders.forEach(o => {
  if (o.status === "scheduled" && o.scheduled_for) {
    const diff = new Date(o.scheduled_for) - now;
    o.canCancel = diff > 60000; // more than 1 min left
  } else {
    o.canCancel = false;
  }
});

      connection.query(bookingsQuery, [userId], (err3, bookings) => {
        if (err3) {
          return next(new ExpressError(500, "Failed to load bookings"));
        }
        const bookingMap = {};

        bookings.forEach(b => {
          if (!bookingMap[b.id]) {
            bookingMap[b.id] = {
              id: b.id,
              date: b.date,
              time_slot: b.time_slot,
              guests: b.guests,
              status: b.status,
              restaurant_name: b.restaurant_name,
              created_at: b.created_at,
              items: []
            };
          }
        
          if (b.item_id) {
            bookingMap[b.id].items.push({
              name: b.item_name,
              quantity: b.quantity
            });
          }
        });
        
        const finalBookings = Object.values(bookingMap)
          .sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
          
          const now = new Date();

        finalBookings.forEach(b => {
        
          if (b.status === "pending") {
            b.canCancel = true;
            return;
          }
        
          if (b.status === "accepted") {
            const bookingDate = new Date(b.date);
            const [hh, mm] = b.time_slot.split(":");
        
            bookingDate.setHours(parseInt(hh), parseInt(mm), 0, 0);
        
            const diffMinutes = (bookingDate - now) / (1000 * 60);
        
            b.canCancel = diffMinutes >= 60; // 1 hour before booking
            return;
          }

          // arrived / completed / rejected / cancelled
          b.canCancel = false;
        });
        res.render("user/profile.ejs", {
          user,
          orders,
          bookings: finalBookings   // ✅ NOW BOOKINGS ALSO AVAILABLE IN EJS
        });
      });
    
    });

  });
};
exports.cancelScheduledOrder = (req, res, next) => {
  const orderId = req.params.id;
  const userId = req.session.user.id;

  // 🔐 verify + only scheduled orders
  const sql = `SELECT status, scheduled_for FROM orders WHERE id=? AND user_id=?`;

  connection.query(sql, [orderId, userId], (err, rows) => {
    if (err) return next(new ExpressError(500, "DB error"));

    if (!rows.length) {
      req.flash("error", "Order not found");
      return res.redirect("/profile");
    }

    const order = rows[0];

    if (order.status !== "scheduled") {
      req.flash("error", "Order can no longer be cancelled");
      return res.redirect("/profile");
    }
    
    // ⏱ TIME LOCK CHECK (1 minute rule)
    const now = new Date();
    const scheduledTime = new Date(order.scheduled_for);
    const diffMs = scheduledTime - now;
    
    if (diffMs <= 60000) { // 60 sec
      req.flash("error", "Cancellation window closed");
      return res.redirect("/profile");
    }
    

    // ✅ safe to cancel
    connection.query(
      "UPDATE orders SET status='cancelled' WHERE id=?",
      [orderId],
      (err2) => {
        if (err2) return next(new ExpressError(500, "Cancel failed"));

        req.flash("success", "Order cancelled successfully");
        res.redirect("/profile");
      }
    );
  });
};

exports.cancelBooking = (req, res) => {
  const bookingId = req.params.id;
  const userId = req.session.user.id;

  const fetchQuery = `
    SELECT date, time_slot, status
    FROM reservations
    WHERE id = ? AND user_id = ?
  `;

  connection.query(fetchQuery, [bookingId, userId], (err, rows) => {
    if (err || rows.length === 0) {
      req.flash("error", "Booking not found");
      return res.redirect("/profile");
    }

    const booking = rows[0];

    if (["arrived", "completed", "rejected", "cancelled"].includes(booking.status)) {
      req.flash("error", "Booking cannot be cancelled now");
      return res.redirect("/profile");
    }

    if (booking.status === "accepted") {
      const bookingDateTime = new Date(
        `${booking.date.toISOString().split("T")[0]} ${booking.time_slot}`
      );

      const diffMinutes = (bookingDateTime - new Date()) / (1000 * 60);

      if (diffMinutes < 60) {
        req.flash("error", "Cancellation time window closed");
        return res.redirect("/profile");
      }
    }

    const updateSql = `
      UPDATE reservations 
      SET status = 'cancelled'
      WHERE id = ? AND user_id = ?
    `;
    const io = req.app.get("io");

    connection.query(updateSql, [bookingId, userId], (err2, result) => {
  if (err2 || result.affectedRows === 0) {
    req.flash("error", "Failed to cancel booking");
    return res.redirect("/profile");
  }

  // 🔥 restaurant id fetch
      connection.query(
        "SELECT restaurant_id FROM reservations WHERE id = ?",
        [bookingId],
        (e2, r2) => {
          if (!e2 && r2.length) {
            const restaurantId = r2[0].restaurant_id;
    
            // ✅ user profile update
            io.to("booking_" + bookingId).emit("bookingStatusUpdate", {
              bookingId,
              status: "cancelled"
            });
    
            // ✅ restaurant dashboard update
            io.to("restaurant_" + restaurantId).emit("bookingStatusUpdate", {
              bookingId,
              status: "cancelled"
            });
          }
    
          req.flash("success", "Booking cancelled successfully");
          res.redirect("/profile");
        }
      );
    });

  });
};



exports.reorderOrder = (req, res, next) => {
  const userId = req.session.user.id;
  const orderId = req.params.orderId;

  const orderQuery = `
    SELECT id, restaurant_id, items, status
    FROM orders
    WHERE id = ? AND user_id = ?
  `;

  connection.query(orderQuery, [orderId, userId], (err, rows) => {
    if (err) return next(new ExpressError(500, "Failed to load order"));
    if (!rows.length) {
      req.flash("error", "Order not found");
      return res.redirect("/profile");
    }

    const order = rows[0];

    if (!["completed", "delivered","cancelled","rejected"].includes(order.status)) {
      req.flash("error", "Only completed orders can be reordered");
      return res.redirect("/profile");
    }

    let items = [];
    try {
      items = typeof order.items === "string"
        ? JSON.parse(order.items)
        : order.items;
    } catch {
      items = [];
    }

    if (!items.length) {
      req.flash("error", "No items found in this order");
      return res.redirect("/profile");
    }

    const restaurantId = order.restaurant_id;

    // 🧹 Clear old cart
    connection.query(
      "DELETE FROM cart_items WHERE user_id = ?",
      [userId],
      (err2) => {
        if (err2) return next(new ExpressError(500, "Failed to reset cart"));

        // ✅ Insert each item again
        items.forEach(item => {

          // 🔎 find item_id using item_name
          const findItemQuery = `
            SELECT id FROM menu_item 
            WHERE item_name = ? AND restaurant_id = ?
            LIMIT 1
          `;

          connection.query(
            findItemQuery,
            [item.item_name, restaurantId],
            (err3, rows3) => {
              if (err3 || !rows3.length) {
                console.log("❌ Item not found:", item.item_name);
                return;
              }

              const itemId = rows3[0].id;

              connection.query(
                `
                INSERT INTO cart_items 
                (user_id, restaurant_id, item_id, quantity)
                VALUES (?, ?, ?, ?)
                `,
                [userId, restaurantId, itemId, item.quantity]
              );
            }
          );
        });

        // ✅ keep restaurant context
        req.session.restaurant_id = restaurantId;

        req.flash("success", "Items added to cart. You can checkout now 🛒");
        return res.redirect("/cart/checkout");
      }
    );
  });
};


exports.addAddress = (req, res, next) => {
  if (!req.session.user) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }

  const { houseNo, street, city, state, pincode, landmark } = req.body;
  const userId = req.session.user.id;

  const insertQuery = `
    INSERT INTO address
    (houseNo, street, city, state, pincode, landmark, user_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `;

  connection.query(
    insertQuery,
    [houseNo, street, city, state, pincode, landmark, userId],
    (err) => {
      if (err) {
        return next(new ExpressError(500, "Failed to add address"));
      }

      connection.query(
        "SELECT * FROM address WHERE user_id = ? ORDER BY id DESC",
        [userId],
        (err2, rows) => {
          if (!err2) {
            req.session.addresses = rows || [];
          }
      
          req.flash("success", "Address added successfully");
          res.redirect("/cart/checkout");
        }
      );
      
    }
  );
};


exports.renderEditProfile = (req, res, next) => {
  if (!req.session.user) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }

  const userId = req.session.user.id;

  connection.query(
    "SELECT firstname, lastname, email, number FROM one WHERE id = ?",
    [userId],
    (err, result) => {
      if (err) {
        return next(new ExpressError(500, "Database error while loading profile"));
      }

      if (!result.length) {
        return next(new ExpressError(404, "User not found"));
      }

      res.render("user/edit.ejs", {
        user: result[0]
      });
    }
  );
};

exports.updatePhone = (req, res, next) => {
  if (!req.session.user) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }

  const { number } = req.body;
  const userId = req.session.user.id;

  if (!number) {
    req.flash("error", "Please enter a valid phone number");
    return res.redirect("back");
  }

  connection.query(
    "UPDATE one SET number = ? WHERE id = ?",
    [number, userId],
    (err) => {
      if (err) {
        return next(new ExpressError(500, "Failed to update phone number"));
      }

      req.flash("success", "Phone number updated");
      res.redirect("back");
    }
  );
};

exports.updateEmail = (req, res, next) => {
  if (!req.session.user) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }

  const { email } = req.body;
  const userId = req.session.user.id;

  if (!email) {
    req.flash("error", "Email cannot be empty");
    return res.redirect("back");
  }

  connection.query(
    "UPDATE one SET email = ? WHERE id = ?",
    [email, userId],
    (err) => {
      if (err) {
        return next(new ExpressError(500, "Failed to update email"));
      }

      req.flash("success", "Email updated successfully");
      res.redirect("back");
    }
  );
};


exports.renderHelp = (req, res, next) => {
  const user = req.session.user || null;

  // 👤 Guest user
  if (!user) {
    return res.render("user/help.ejs", {
      user: null
    });
  }

  // 🔐 Logged in user
  const userId = user.id;

  connection.query(
    "SELECT firstname, email FROM one WHERE id = ?",
    [userId],
    (err, result) => {
      if (err) {
        return next(new ExpressError(500, "Failed to load help page"));
      }

      if (!result.length) {
        return res.render("user/help.ejs", {
          user: null
        });
      }

      res.render("user/help.ejs", {
        user: result[0]
      });
    }
  );
};



function generateRandomString(length) {
  const characters = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  return Array.from({ length }, () => characters[Math.floor(Math.random() * characters.length)]).join('');
}

exports.renderForgot = (req, res) => {
  const captcha = generateRandomString(5);
  req.session.captcha = captcha;

  res.render("user/forgot.ejs", {
    randomString: captcha
  });
};


exports.forgot = (req, res, next) => {
  const { email, textarea } = req.body;

  if (textarea !== req.session.captcha) {
    req.flash("error", "Wrong captcha");
    return res.redirect("/forgot");
  }

  connection.query(
    "SELECT id FROM one WHERE email = ?",
    [email],
    (err, result) => {
      if (err) return next(new ExpressError(500, "Database error"));

      if (!result.length) {
        req.flash("error", "Email not registered");
        return res.redirect("/forgot");
      }

      const token = generateRandomString(32);
      const expiry = new Date(Date.now() + 15 * 60 * 1000); // 15 min

      connection.query(
        "UPDATE one SET reset_token = ?, reset_token_expiry = ? WHERE id = ?",
        [token, expiry, result[0].id],
        (err2) => {
          if (err2) return next(new ExpressError(500, "Token save failed"));

          // 🚨 Email sending later (for now show reset page)
          res.redirect(`/reset-password?token=${token}`);
        }
      );
    }
  );
};
exports.renderResetPassword = (req, res) => {
  const { token } = req.query;

  if (!token) {
    req.flash("error", "Invalid reset link");
    return res.redirect("/forgot");
  }

  // 📌 YAHI WO LINE HAI
  res.render("user/reset.ejs", { token });
};

exports.resetPassword = async (req, res, next) => {
  const { password, confirm, token } = req.body;

  if (!password || !confirm) {
    req.flash("error", "Password cannot be empty");
    return res.redirect("back");
  }

  if (password !== confirm) {
    req.flash("error", "Passwords do not match");
    return res.redirect("back");
  }

  const hashedPassword = await bcrypt.hash(password, 10);

  connection.query(
    `
    UPDATE one
    SET password = ?, reset_token = NULL, reset_token_expiry = NULL
    WHERE reset_token = ? AND reset_token_expiry > NOW()
    `,
    [hashedPassword, token],
    (err, result) => {
      if (err) {
        return next(new ExpressError(500, "Failed to reset password"));
      }

      if (result.affectedRows === 0) {
        req.flash("error", "Reset link expired or invalid");
        return res.redirect("/forgot");
      }

      req.flash("success", "Password reset successful");
      res.redirect("/login");
    }
  );
};

exports.trackOrder = (req, res, next) => {
  if (!req.session.user) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }

  const orderId = req.params.id;
  const userId = req.session.user.id;

  connection.query(
    "SELECT * FROM orders WHERE id = ?",
    [orderId],
    (err, rows) => {
      if (err) {
        return next(new ExpressError(500, "Failed to load order"));
      }

      if (!rows.length) {
        return next(new ExpressError(404, "Order not found"));
      }

      const o = rows[0];

      // 🔐 ownership check
      if (o.user_id !== userId) {
        return next(new ExpressError(403, "Unauthorized access to order"));
      }

      let items = [];
      try {
        items = typeof o.items === "string" ? JSON.parse(o.items) : o.items;
      } catch {
        items = [];
      }

      const timestamps = {
        pending: o.created_at,
        accepted: o.accepted_at,
        preparing: o.preparing_at,
        ready: o.ready_at,
        picked_up: o.picked_up_at,
        out_for_delivery: o.out_for_delivery_at,
        delivered: o.delivered_at
      };

      const statusForTimeline =
        o.status === "completed" ? "delivered" : o.status;

      res.render("user/track-order", {
        orderId,
        currentStatus: statusForTimeline,
        createdAt: o.created_at,
        items,
        timestamps,
        scheduledFor: o.scheduled_for,
        rawStatus: o.status
      });
    }
  );
};

exports.paymentSuccess = (req, res, next) => {

  if (!req.session.user || !req.session.restaurant_id) {
    req.flash("error", "Session expired. Please login again");
    return res.redirect("/login");
  }

  const io = req.app.get("io");
  const userId = req.session.user.id;
  const restaurantId = req.session.restaurant_id;

  // ✅ scheduling from session
  let orderStatus = "pending";
  let isScheduled = false;
  let scheduledFor = null;

  if (req.session.orderSchedule) {
    orderStatus = "scheduled";
    isScheduled = true;
    scheduledFor = req.session.orderSchedule.scheduled_for;
  }

  const cartQuery = `
    SELECT m.item_name, m.price, c.quantity
    FROM cart_items c
    JOIN menu_item m ON c.item_id = m.id
    WHERE c.user_id = ? AND c.restaurant_id = ?
  `;

  connection.query(cartQuery, [userId, restaurantId], (err, cartItems) => {
    if (err) return next(new ExpressError(500, "Failed to load cart items"));

    if (!cartItems.length) {
      req.flash("error", "Your cart is empty");
      return res.redirect("/cart/checkout");
    }

    const itemsJSON = JSON.stringify(cartItems);
    const total = cartItems.reduce((sum, i) => sum + i.price * i.quantity, 0);

    connection.query(
      "SELECT id FROM address WHERE user_id = ? LIMIT 1",
      [userId],
      (err2, addr) => {
        if (err2) return next(new ExpressError(500, "Failed to fetch address"));

        const addressId = addr.length ? addr[0].id : null;

        connection.query(
          `
          INSERT INTO orders
          (user_id, restaurant_id, items, total_price, address_id,
           status, is_scheduled, scheduled_for, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, NOW())
          `,
          [
            userId,
            restaurantId,
            itemsJSON,
            total,
            addressId,
            orderStatus,
            isScheduled,
            scheduledFor
          ],
          (err3, result) => {
            
            if (err3) {
              console.error("ORDER INSERT ERROR:", err3);

              return next(new ExpressError(500, "Failed to place order"));
            }

            const orderId = result.insertId;

            // 🔥 realtime only if instant
            if (orderStatus === "pending") {
              io.to("restaurant_" + restaurantId).emit("newOrder", {
                id: orderId,
                restaurant_id: restaurantId,
                items: cartItems,
                total_price: total,
                status: "pending"
              });
            }

            // 🧹 clear cart
            connection.query(
              "DELETE FROM cart_items WHERE user_id = ? AND restaurant_id = ?",
              [userId, restaurantId]
            );

            // 🧹 clear schedule session
            delete req.session.orderSchedule;

            res.render("user/success.ejs", {
              user: req.session.user,
              orderId
            });
          }
        );
      }
    );
  });
};




exports.getOrderStatus = (req, res, next) => {
  if (!req.session.user) {
    return res.status(401).json({});
  }

  const orderId = req.params.orderId;
  const userId = req.session.user.id;

  connection.query(
    "SELECT status, updated_at, user_id FROM orders WHERE id = ?",
    [orderId],
    (err, rows) => {
      if (err) {
        return next(new ExpressError(500, "Failed to fetch order status"));
      }

      if (!rows.length) {
        return res.status(404).json({});
      }

      const order = rows[0];

      // 🔐 ownership check
      if (order.user_id !== userId) {
        return res.status(403).json({});
      }

      res.json({
        status: order.status,
        updated_at: order.updated_at
      });
    }
  );
};

