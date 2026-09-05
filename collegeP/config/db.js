// config/db.js
// 1. Importing MySQL2 driver
const mysql = require("mysql2");

// Validate required environment variables (fail-fast)
const requiredEnvVars = ['DB_HOST', 'DB_USER', 'DB_NAME'];
for (const envVar of requiredEnvVars) {
    if (!process.env[envVar]) {
        console.warn(`⚠️ Warning: Missing required database environment variable: ${envVar}`);
    }
}

// 2. Creating DB Connection Pool
const connection = mysql.createPool({
    host: process.env.DB_HOST,
    user: process.env.DB_USER,
    database: process.env.DB_NAME,
    password: process.env.DB_PASSWORD,
    port: process.env.DB_PORT || 3306,
    connectionLimit: 10,
    queueLimit: 0
});

module.exports = connection; // Exporting the pool (consumers still use connection.query)