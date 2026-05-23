const express = require("express");
const router = express.Router();
const adminController = require("../controllers/admin");
const {isPlatformAdmin}  = require("../middlewares");
const wrapAsync = require("../utils/wrapAsync");
// platform mean apna admin panel work
router.get("/platform-admin/login", adminController.renderLogin);
router.post("/platform-admin/login", adminController.login);


router.get("/platform-admin/dashboard", isPlatformAdmin,adminController.dashboard );

router.post("/platform-admin/approve/:id", isPlatformAdmin,wrapAsync(adminController.approve));

router.post("/platform-admin/reject/:id", isPlatformAdmin,adminController.reject );

module.exports = router;