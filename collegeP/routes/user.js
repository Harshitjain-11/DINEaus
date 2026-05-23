const express = require("express");
const router = express.Router();

const userController = require("../controllers/user.js");
const wrapAsync = require("../utils/wrapAsync.js");
const { isLoggedIn } = require("../middlewares.js");

router.get("/sign", userController.renderSignup);
router.post("/sign", wrapAsync(userController.signup));
router.get("/login", userController.renderLogin);
router.post("/login", wrapAsync(userController.login));
router.get("/forgot", userController.renderForgot);
router.post("/forgot", userController.forgot);

router.get("/reset-password", userController.renderResetPassword);
router.post("/reset-password", wrapAsync(userController.resetPassword));
router.get("/logout", userController.logout);

router.post("/set-schedule", (req, res) => {
  req.session.orderSchedule = {
    is_scheduled: true,
    scheduled_for: req.body.scheduled_for
  };
  res.json({ ok: true });
});
// After login
router.get("/home", userController.renderHome);

// ❌ email removed
router.get("/restaurant/:id", userController.showRestaurant);
router.get("/reserve/:id", isLoggedIn, userController.renderReservationForm);

// APIs
router.get("/restaurant-seats", userController.getRestaurantSeats);
router.get("/reservation/slots", userController.getReservationSlots);
router.post("/reservation/create-full", isLoggedIn, userController.createReservation);

// Search
router.get("/search", userController.renderSearch);
router.get("/search-ajax", userController.searchAjax);

// Cart
router.get("/cart/checkout", userController.renderCart);
router.post("/cart/update", userController.updateCart);
router.delete("/cart/delete", isLoggedIn, userController.deleteAddress);

// Payment
router.get("/payment", isLoggedIn, userController.renderPayment);
router.get("/payment/success", isLoggedIn, userController.paymentSuccess);

// Profile (❌ firstname removed)
router.get("/profile", isLoggedIn, userController.renderProfile);
// Reorder
router.get("/orders/reorder/:orderId",isLoggedIn,userController.reorderOrder);

router.post("/profile", isLoggedIn, userController.addAddress);

router.get("/profile/edit", isLoggedIn, userController.renderEditProfile);
router.patch("/profile/edit/number", isLoggedIn, userController.updatePhone);
router.patch("/profile/edit/email", isLoggedIn, userController.updateEmail);
router.post("/order/:id/cancel", isLoggedIn, userController.cancelScheduledOrder);
router.post("/booking/:id/cancel", isLoggedIn, userController.cancelBooking);
router.get("/help", userController.renderHelp);

// Order tracking
router.get("/track-order/:id", isLoggedIn, userController.trackOrder);
router.get("/api/order-status/:orderId", isLoggedIn, userController.getOrderStatus);



module.exports = router;
