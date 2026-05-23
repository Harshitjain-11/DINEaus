const connection = require("../config/db");
const ExpressError = require("../utils/ExpressError");
const bcrypt = require("bcrypt");

exports.renderLogin = (req, res) => {
  res.render("admin/platform-admin-login");
};
exports.login = (req, res, next) => {
  const { email, password } = req.body;

  if (!email || !password) {
    req.flash("error", "Email and password required");
    return res.redirect("/platform-admin/login");
  }

  connection.query(
    "SELECT * FROM platform_admin WHERE email = ?",
    [email],
    async (err, rows) => {
      if (err) return next(new ExpressError(500, "Database error"));

      if (!rows.length) {
        req.flash("error", "Invalid credentials");
        return res.redirect("/platform-admin/login");
      }

      const admin = rows[0];
      const match = await bcrypt.compare(password, admin.password);

      if (!match) {
        req.flash("error", "Invalid credentials");
        return res.redirect("/platform-admin/login");
      }

      req.session.platformAdmin = {
        id: admin.id,
        email: admin.email,
        role: admin.role
      };

      res.redirect("/platform-admin/dashboard");
    }
  );
};
exports.dashboard = (req, res, next) => {
  connection.query(
    "SELECT * FROM restaurant WHERE status = 'pending'",
    (err, restaurants) => {
      if (err) return next(new ExpressError(500, "DB error"));

      res.render("admin/platform-admin-dashboard", { restaurants });
    }
  );
};
exports.approve = async (req, res, next) => {
  const restaurantId = req.params.id;

  connection.query(
    "SELECT * FROM restaurant WHERE id = ?",
    [restaurantId],
    async (err, rows) => {
      if (err) return next(new ExpressError(500, "DB error"));
      if (!rows.length) return next(new ExpressError(404, "Restaurant not found"));

      const restaurant = rows[0];

      if (restaurant.status === "approved") {
        req.flash("error", "Restaurant already approved");
        return res.redirect("/platform-admin/dashboard");
      }

      const tempPassword = await bcrypt.hash("1234", 10);

      connection.query(
        "INSERT INTO restaurant_admin (restaurant_id, email, password, role) VALUES (?, ?, ?, 'owner')",
        [restaurantId, restaurant.email, tempPassword],
        (err2) => {
          if (err2) return next(new ExpressError(500, "Admin create error"));

          connection.query(
            "UPDATE restaurant SET status='approved' WHERE id = ?",
            [restaurantId]
          );

          req.flash("success", "Restaurant approved & admin created");
          res.redirect("/platform-admin/dashboard");
        }
      );
    }
  );
};
exports.reject = (req, res, next) => {
  connection.query(
    "UPDATE restaurant SET status='rejected' WHERE id = ?",
    [req.params.id],
    (err) => {
      if (err) return next(new ExpressError(500, "DB error"));

      req.flash("success", "Restaurant rejected");
      res.redirect("/platform-admin/dashboard");
    }
  );
};
