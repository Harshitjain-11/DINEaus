const express = require("express");
const router = express.Router();

const deliveryController = require("../controllers/delivery");
const { isDeliveryPartner } = require("../middlewares");

const wrapAsync = require("../utils/wrapAsync");
// ab delivery partner panel banega
router.get("/delivery/register", (req, res) => {
    res.render("delivery/delivery-register.ejs");
});
router.post("/delivery/register", wrapAsync(deliveryController.register));


router.get("/delivery/login", deliveryController.renderLogin);
router.post("/delivery/login", deliveryController.login);


router.get("/delivery/dashboard/:id", isDeliveryPartner, deliveryController.dashboard);
router.get("/delivery/orders/:id", isDeliveryPartner, deliveryController.order);

router.post("/delivery/order/:id/accept", isDeliveryPartner, deliveryController.acceptOrder);
router.post("/delivery/order/:id/pickup", isDeliveryPartner, deliveryController.pickupOrder);
router.post("/delivery/order/:id/out-for-delivery", isDeliveryPartner, deliveryController.outForDelivery);
router.post("/delivery/order/:id/delivered", isDeliveryPartner, deliveryController.delivered);

module.exports = router;