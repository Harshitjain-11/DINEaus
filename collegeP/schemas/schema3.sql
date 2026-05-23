
CREATE TABLE menu_item (
  id INT AUTO_INCREMENT PRIMARY KEY,
  restaurant_id INT,
  item_name VARCHAR(255),
  price DECIMAL(10, 2),
  costfortwo INT,
  vegNonveg VARCHAR(20),
  cuisine varchar(90),
  menu_image VARCHAR(255) NULL,
  common_image VARCHAR(255) NULL,
  description TEXT NULL,
  is_available BOOLEAN DEFAULT TRUE,
  is_veg BOOLEAN DEFAULT TRUE
);
CREATE TABLE restaurant (
  id INT AUTO_INCREMENT PRIMARY KEY,
  ownerName VARCHAR(255),
  name VARCHAR(255),
  Address VARCHAR(255),
  email varchar(100) UNIQUE,
  ownerNumber VARCHAR(15),
  location VARCHAR(100),
  image_url VARCHAR(500),
  status ENUM('pending', 'approved', 'rejected') DEFAULT 'pending',
  latitude DECIMAL(10,8) NULL,
  longitude DECIMAL(11,8) NULL
);
CREATE TABLE cart_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT,
  restaurant_id INT,
  item_id INT,
  quantity INT DEFAULT 1,
  FOREIGN KEY (user_id) REFERENCES one(id),
  FOREIGN KEY (restaurant_id) REFERENCES restaurant(id),
  FOREIGN KEY (item_id) REFERENCES menu_item(id)
);

