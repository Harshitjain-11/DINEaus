// 1. Importing MySQL2 driver - Preferred over 'mysql' for performance and async support.
const mysql = require("mysql2");

// 2. Creating DB connection or Database Configuration object
const connection = mysql.createConnection({
    host: "localhost",
    user: "root",
    database: "college_practice",
    password: "harshit@123"
});

// 3. Establishing the connection
// connection.connect() is used to verify if the credentials and DB server are reachable.
connection.connect((err)=>{
    if(err){
        console.error("❌ DB connection failed:", err.message);
    }else{
        console.log("✅ DB connected!");
    }
});

module.exports = connection;// 4. Exporting the connection instance (Singleton Pattern)
// This allows other files to use the SAME database connection via require().