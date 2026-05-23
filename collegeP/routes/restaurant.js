const express = require("express");
const router = express.Router();

const upload = require("../utils/multer");
const restaurantController = require("../controllers/restaurant");
const wrapAsync = require("../utils/wrapAsync");
const {isRestaurantAdmin} = require("../middlewares.js");

router.get("/dineous-partner",(req,res)=>{
  res.render("restaurant/dineous-partner.ejs");
})
router.get("/resturantinformation",(req,res)=>{
  res.render("restaurant/resturantinformation.ejs");
})
router.get("/resturant-document",(req,res)=>{
  res.render("restaurant/resturant-document.ejs");
})
router.get("/resturant-menu",(req,res)=>{
  res.render("restaurant/resturant-menu.ejs");
})

router.post("/add-restaurant", restaurantController.addRestaurant);
router.post("/upload-menu", upload.single("menuFile"), wrapAsync(restaurantController.uploadMenu));


router.get("/restaurant-admin/login", (req, res) =>
  res.render("restaurant/restaurant-admin-login")
);
router.post("/restaurant-admin/login", restaurantController.adminLogin);

router.get("/restaurant-admin/dashboard",  isRestaurantAdmin,restaurantController.dashboard);

router.post("/restaurant-admin/order/:id/accept", isRestaurantAdmin, restaurantController.acceptOrder);
router.post("/restaurant-admin/order/:id/reject", isRestaurantAdmin, restaurantController.rejectOrder);
router.post("/restaurant-admin/order/:id/preparing", isRestaurantAdmin, restaurantController.preparingOrder);
router.post("/restaurant-admin/order/:id/ready", isRestaurantAdmin, restaurantController.readyOrder);
router.post("/restaurant-admin/order/:id/completed", isRestaurantAdmin, restaurantController.completedOrder);
router.get("/restaurant-admin/orders/history", isRestaurantAdmin, restaurantController.orderHistory);


router.post("/restaurant-admin/booking/:id/accept", isRestaurantAdmin, restaurantController.acceptBooking);
router.post("/restaurant-admin/booking/:id/reject", isRestaurantAdmin, restaurantController.rejectBooking);
router.post(
  "/restaurant-admin/booking/:id/arrived",
  isRestaurantAdmin,
  restaurantController.markBookingArrived
);

router.post(
  "/restaurant-admin/booking/:id/completed",
  isRestaurantAdmin,
  restaurantController.markBookingCompleted
);


module.exports = router;