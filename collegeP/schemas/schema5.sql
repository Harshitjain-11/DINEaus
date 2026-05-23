CREATE TABLE platform_admin (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(100) UNIQUE,
    password VARCHAR(255),
    name VARCHAR(100)
);

CREATE TABLE IF NOT EXISTS restaurant_admin (
  id INT AUTO_INCREMENT PRIMARY KEY,
  restaurant_id INT NOT NULL,
  email VARCHAR(100) NOT NULL UNIQUE,
  password VARCHAR(255) NOT NULL,
  role ENUM('owner','manager','staff') DEFAULT 'owner',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (restaurant_id) REFERENCES restaurant(id) ON DELETE CASCADE
);
CREATE TABLE orders (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  restaurant_id INT NOT NULL,
  items JSON NOT NULL,
  total_price DECIMAL(10,2) NOT NULL,
  address_id INT,
  status ENUM('scheduled','pending','accepted','preparing','ready','out_for_delivery','picked_up','delivered','completed','rejected','cancelled') DEFAULT 'pending',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  delivery_partner_id INT NULL,
  accepted_at DATETIME NULL,
  preparing_at DATETIME NULL,
  ready_at DATETIME NULL,
  picked_up_at DATETIME NULL,
  out_for_delivery_at DATETIME NULL,
  delivered_at DATETIME NULL,

  
  delivery_lat DECIMAL(10,7) NULL,
  delivery_lng DECIMAL(10,7) NULL,
  delivery_last_update DATETIME NULL,

  FOREIGN KEY (user_id) REFERENCES one(id),
  FOREIGN KEY (restaurant_id) REFERENCES restaurant(id),
  FOREIGN KEY (address_id) REFERENCES address(id),
  is_scheduled BOOLEAN DEFAULT false,
  scheduled_for DATETIME NULL
);
