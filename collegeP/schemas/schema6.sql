CREATE TABLE delivery_partner (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(255),
  phone VARCHAR(20),
  vehicle VARCHAR(50),
  email VARCHAR(255),
  password VARCHAR(255)
);
UPDATE orders
SET
   is_scheduled = true,
   scheduled_for = NOW() + INTERVAL 2 MINUTE
WHERE id = 2;