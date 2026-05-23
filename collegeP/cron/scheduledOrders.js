const cron = require("node-cron");
const connection = require("../config/db");

module.exports = (io) => {

  cron.schedule("* * * * *", () => {

    const sql = `
      SELECT * FROM orders
      WHERE status='scheduled'
      AND scheduled_for <= NOW()
    `;

    connection.query(sql, (err, orders) => {
      if (err) return console.error(err);

      orders.forEach(o => {

        connection.query(
          "UPDATE orders SET status='pending' WHERE id=?",
          [o.id]
        );

        io.to("restaurant_" + o.restaurant_id).emit("newOrder", o);
        io.to("user_" + o.user_id).emit("profileOrderUpdate", {
          orderId: o.id,
          status: "pending"
        });
        
      });
    });
  });

};
  