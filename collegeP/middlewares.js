module.exports.isLoggedIn = (req, res, next) => {
  if (!req.session.user) {
    req.flash("error", "Please login first");
    return res.redirect("/login");
  }
  next();
};
module.exports.isRestaurantAdmin = (req, res, next) => {
  if (!req.session.restaurantAdmin) {
    req.flash("error", "Please login as restaurant admin");
    return res.redirect("/restaurant-admin/login");
  }
  next();
};
module.exports.isDeliveryPartner = (req, res, next) => {
  if (!req.session.deliveryPartner) {
    req.flash("error", "Please login as delivery partner");
    return res.redirect("/delivery/login");
  }
  next();
};

// middleware/admin.js
module.exports.isPlatformAdmin = (req, res, next) => {
  if (!req.session.platformAdmin) {
    req.flash("error", "Please login first");
    return res.redirect("/platform-admin/login");
  }
  next();
};
exports.uiNavigationGuard = (req, res, next) => {

  const restrictedPages = [
    "/payment",
    "/profile",
    "/cart",
    "/cart/checkout",
    "/help",
    "/track-order"
  ];

  const path = req.path;
  const referer = req.headers.referer;

  const isRestricted = restrictedPages.some(p =>
    path.startsWith(p)
  );

  // ✅ User logged in
  // ❌ Restricted page
  // ❌ No referer (means manually URL dala)
  if (req.session.user && isRestricted && !referer) {
    req.flash("error", "Please use app navigation");
    return res.redirect("/home");
  }

  next();
};
