
CREATE TABLE one (
  id INT AUTO_INCREMENT PRIMARY KEY,
  firstname VARCHAR(100),
  lastname VARCHAR(100),
  email VARCHAR(100) UNIQUE,
  number BIGINT,
  password VARCHAR(100),
  reset_token VARCHAR(255),
  reset_token_expiry DATETIME
);
CREATE TABLE Address (
  id INT AUTO_INCREMENT PRIMARY KEY,
  houseNo INT,
  street VARCHAR(100),
  city VARCHAR(100),
  state VARCHAR(100),
  pincode INT,
  landmark VARCHAR(255),
  user_id INT,
  FOREIGN KEY (user_id) REFERENCES one(id) ON DELETE CASCADE,
  latitude DECIMAL(10,8),
  longitude DECIMAL(11,8)
);
