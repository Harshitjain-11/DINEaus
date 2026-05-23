CREATE TABLE IF NOT EXISTS reservations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    restaurant_id INT NOT NULL,
    customer_name VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(30) NOT NULL,
    date DATE NOT NULL,
    time_slot VARCHAR(20) NOT NULL,
    guests INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (restaurant_id) REFERENCES restaurant(id),
    seat_id INT NULL,
    user_id INT,
    FOREIGN KEY (user_id) REFERENCES one(id),
    status ENUM('pending','accepted','arrived','completed','rejected','cancelled') DEFAULT 'pending'
);

CREATE TABLE restaurant_seats (
  id INT AUTO_INCREMENT PRIMARY KEY,
  restaurant_id INT NOT NULL,
  seat_name VARCHAR(100),
  seat_type VARCHAR(50),
  image_url VARCHAR(255),
  is_available TINYINT DEFAULT 1,
  FOREIGN KEY (restaurant_id) REFERENCES restaurant(id)
);

CREATE TABLE reservation_preorders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  reservation_id INT NOT NULL,
  item_id INT NOT NULL,
  quantity INT NOT NULL,
  FOREIGN KEY (reservation_id) REFERENCES reservations(id),
  FOREIGN KEY (item_id) REFERENCES menu_item(id)
);