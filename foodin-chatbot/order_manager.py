"""
PRODUCTION OrderManager - 100% DINEaus Compatible
Database: college_practice
Fully aligned with your actual production schema
"""

import mysql.connector
from mysql.connector import errorcode
import json
from datetime import datetime
from typing import Optional, Dict, Any, List

class OrderManager:
    def __init__(self, db_config: dict):
        self.db_config = db_config
        self._conn = None
        self._connect()

    def _connect(self):
        try:
            self._conn = mysql.connector.connect(**self.db_config)
            print("✅ MySQL connection established")
        except mysql.connector.Error as err:
            print(f"❌ MySQL connection error: {err}")
            raise

    def _ensure_connection(self):
        """Reconnect if connection dropped."""
        try:
            self._conn.ping(reconnect=True, attempts=3, delay=2)
        except Exception:
            self._connect()

    def close(self):
        if self._conn:
            self._conn.close()

    # ===============================
    # RESTAURANT & MENU METHODS
    # ===============================

    def get_restaurants(self) -> List[Dict[str, Any]]:
        """Get all approved restaurants with image_url."""
        self._ensure_connection()
        cursor = self._conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT id, name, location, image_url "
                "FROM restaurant WHERE status = 'approved' ORDER BY id"
            )
            rows = cursor.fetchall()
            return rows if rows else []
        except Exception as e:
            print(f"Error fetching restaurants: {e}")
            return []
        finally:
            cursor.close()

    def get_menu(self, restaurant_id: int) -> List[Dict[str, Any]]:
        """Get available menu items for a restaurant."""
        self._ensure_connection()
        cursor = self._conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT item_name, price FROM menu_item "
                "WHERE restaurant_id = %s AND is_available = TRUE",
                (restaurant_id,)
            )
            rows = cursor.fetchall()
            return rows if rows else []
        except Exception as e:
            print(f"Error fetching menu for restaurant {restaurant_id}: {e}")
            return []
        finally:
            cursor.close()

    # ===============================
    # ORDER METHODS
    # ===============================

    def add_order(self, user_id: int, restaurant_id: int,
                  items: List[Dict[str, Any]], total_price: float,
                  address_id: int = None) -> int:
        """Create new order."""
        self._ensure_connection()
        items_json = json.dumps(items, default=str)

        if not user_id or user_id == "anonymous":
            user_id = 1

        cursor = self._conn.cursor()
        try:
            print(f"📝 Creating Order: User={user_id} Restaurant={restaurant_id} Items={len(items)} Total=₹{total_price}")
            cursor.execute(
                """
                INSERT INTO orders
                (user_id, restaurant_id, items, total_price, address_id, status, created_at)
                VALUES (%s, %s, %s, %s, %s, 'pending', NOW())
                """,
                (user_id, restaurant_id, items_json, total_price, address_id)
            )
            self._conn.commit()
            order_id = cursor.lastrowid
            print(f"✅ Order #{order_id} created!")
            return order_id
        except Exception as e:
            self._conn.rollback()
            print(f"❌ Error creating order: {e}")
            raise
        finally:
            cursor.close()

    def add_cart_items(self, user_id: int, restaurant_id: int,
                       items: List[Dict[str, Any]]) -> int:
        """Insert items into cart_items table by resolving menu_item ids."""
        self._ensure_connection()
        if not items:
            return 0
        cursor = self._conn.cursor()
        added = 0
        try:
            for item in items:
                name = item.get("item_name")
                qty = int(item.get("quantity", 1) or 1)
                if not name:
                    continue
                cursor.execute(
                    "SELECT id FROM menu_item WHERE restaurant_id = %s AND LOWER(item_name) = LOWER(%s) LIMIT 1",
                    (restaurant_id, name)
                )
                row = cursor.fetchone()
                if not row:
                    continue
                item_id = row[0]
                cursor.execute(
                    "INSERT INTO cart_items (user_id, restaurant_id, item_id, quantity) VALUES (%s, %s, %s, %s)",
                    (user_id, restaurant_id, item_id, qty)
                )
                added += 1
            self._conn.commit()
            return added
        except Exception as e:
            self._conn.rollback()
            print(f"❌ Error inserting cart_items: {e}")
            return 0
        finally:
            cursor.close()

    def get_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve order by id."""
        self._ensure_connection()
        cursor = self._conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))
            row = cursor.fetchone()
            if not row:
                return None
            if row.get('items'):
                try:
                    row['items'] = json.loads(row['items'])
                except:
                    row['items'] = []
            row['order_id'] = row['id']
            row['total'] = row.get('total_price', 0)
            return row
        finally:
            cursor.close()

    def confirm_order(self, order_id: int) -> bool:
        """Change order status pending → accepted."""
        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            cursor.execute("SELECT status FROM orders WHERE id = %s", (order_id,))
            row = cursor.fetchone()
            if not row:
                return False
            try:
                cursor.execute(
                    "UPDATE orders SET status = 'accepted', accepted_at = NOW() WHERE id = %s",
                    (order_id,)
                )
            except:
                cursor.execute(
                    "UPDATE orders SET status = 'accepted' WHERE id = %s",
                    (order_id,)
                )
            self._conn.commit()
            print(f"✅ Order #{order_id} confirmed")
            return True
        except Exception as e:
            self._conn.rollback()
            print(f"❌ Error confirming order: {e}")
            raise
        finally:
            cursor.close()

    def cancel_order(self, order_id: int, reason: Optional[str] = None) -> bool:
        """Cancel order."""
        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE orders SET status = 'cancelled'
                WHERE id = %s AND status NOT IN ('delivered', 'completed')
                """,
                (order_id,)
            )
            if cursor.rowcount == 0:
                return False
            self._conn.commit()
            print(f"✅ Order #{order_id} cancelled")
            return True
        except Exception as e:
            self._conn.rollback()
            print(f"❌ Error cancelling order: {e}")
            raise
        finally:
            cursor.close()

    def track_order(self, order_id: int) -> Optional[Dict[str, Any]]:
        """Track order by id."""
        return self.get_order(order_id)

    def get_latest_order_for_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Fetch most recent order for a user."""
        self._ensure_connection()
        cursor = self._conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT * FROM orders WHERE user_id = %s ORDER BY id DESC LIMIT 1",
                (user_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            if row.get("items"):
                try:
                    row["items"] = json.loads(row["items"])
                except Exception:
                    row["items"] = []
            row["order_id"] = row.get("id")
            row["total"] = row.get("total_price", 0)
            return row
        finally:
            cursor.close()

    def get_latest_active_order_for_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Fetch most recent non-final order for a user."""
        self._ensure_connection()
        cursor = self._conn.cursor(dictionary=True)
        try:
            cursor.execute(
                "SELECT * FROM orders WHERE user_id = %s "
                "AND status NOT IN ('delivered', 'completed', 'cancelled') "
                "ORDER BY id DESC LIMIT 1",
                (user_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            if row.get("items"):
                try:
                    row["items"] = json.loads(row["items"])
                except Exception:
                    row["items"] = []
            row["order_id"] = row.get("id")
            row["total"] = row.get("total_price", 0)
            return row
        finally:
            cursor.close()

    def update_order_status(self, order_id: int, new_status: str,
                            update_timestamp: bool = True) -> bool:
        """Update order to any valid status."""
        valid_statuses = [
            "scheduled", "pending", "accepted", "preparing", "ready",
            "out_for_delivery", "picked_up", "delivered",
            "completed", "rejected", "cancelled"
        ]
        if new_status not in valid_statuses:
            print(f"❌ Invalid status: {new_status}")
            return False

        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            timestamp_map = {
                'accepted': 'accepted_at', 'preparing': 'preparing_at',
                'ready': 'ready_at', 'picked_up': 'picked_up_at',
                'out_for_delivery': 'out_for_delivery_at', 'delivered': 'delivered_at'
            }
            timestamp_col = timestamp_map.get(new_status)
            if timestamp_col and update_timestamp:
                try:
                    cursor.execute(
                        f"UPDATE orders SET status = %s, {timestamp_col} = NOW() WHERE id = %s",
                        (new_status, order_id)
                    )
                except:
                    cursor.execute(
                        "UPDATE orders SET status = %s WHERE id = %s",
                        (new_status, order_id)
                    )
            else:
                cursor.execute(
                    "UPDATE orders SET status = %s WHERE id = %s",
                    (new_status, order_id)
                )
            self._conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            self._conn.rollback()
            print(f"❌ Error updating status: {e}")
            raise
        finally:
            cursor.close()

    # ===============================
    # RESERVATION METHODS
    # ===============================

    def book_table(self, user_id: int, restaurant_id: int,
                   customer_name: str, customer_phone: str,
                   booking_date: str, time_slot: str, guests: int) -> int:
        """Create table reservation."""
        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            if not user_id or user_id == "anonymous":
                user_id = 1

            print(f"📅 Creating Reservation: Restaurant={restaurant_id} Date={booking_date} Time={time_slot} Guests={guests}")
            cursor.execute(
                """
                INSERT INTO reservations
                (restaurant_id, customer_name, customer_phone, date, time_slot,
                 guests, user_id, status, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW())
                """,
                (restaurant_id, customer_name, customer_phone,
                 booking_date, time_slot, guests, user_id)
            )
            self._conn.commit()
            booking_id = cursor.lastrowid
            print(f"✅ Reservation #{booking_id} created!")
            return booking_id
        except Exception as e:
            self._conn.rollback()
            # Retry with fallback user_id if foreign key fails.
            if "foreign key constraint fails" in str(e).lower() or "1452" in str(e):
                try:
                    cursor.execute(
                        """
                        INSERT INTO reservations
                        (restaurant_id, customer_name, customer_phone, date, time_slot,
                         guests, user_id, status, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', NOW())
                        """,
                        (restaurant_id, customer_name, customer_phone,
                         booking_date, time_slot, guests, 1)
                    )
                    self._conn.commit()
                    booking_id = cursor.lastrowid
                    print(f"✅ Reservation #{booking_id} created with fallback user_id")
                    return booking_id
                except Exception:
                    self._conn.rollback()
            print(f"❌ Error creating reservation: {e}")
            raise
        finally:
            cursor.close()

    def get_reservation(self, reservation_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve reservation by id."""
        self._ensure_connection()
        cursor = self._conn.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM reservations WHERE id = %s", (reservation_id,))
            return cursor.fetchone()
        finally:
            cursor.close()

    def cancel_reservation(self, reservation_id: int) -> bool:
        """Cancel reservation."""
        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE reservations SET status = 'cancelled'
                WHERE id = %s AND status NOT IN ('completed', 'cancelled')
                """,
                (reservation_id,)
            )
            self._conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            self._conn.rollback()
            print(f"❌ Error cancelling reservation: {e}")
            raise
        finally:
            cursor.close()

    def update_reservation_status(self, reservation_id: int, new_status: str) -> bool:
        """Update reservation status."""
        valid_statuses = ['pending', 'accepted', 'arrived', 'completed', 'rejected', 'cancelled']
        if new_status not in valid_statuses:
            return False

        self._ensure_connection()
        cursor = self._conn.cursor()
        try:
            cursor.execute(
                "UPDATE reservations SET status = %s WHERE id = %s",
                (new_status, reservation_id)
            )
            self._conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            self._conn.rollback()
            print(f"❌ Error updating reservation: {e}")
            raise
        finally:
            cursor.close()

    def add_reservation_preorders(self, reservation_id: int,
                                  items: List[Dict[str, Any]]) -> int:
        """Attach preorder items to a reservation."""
        self._ensure_connection()
        if not items:
            return 0
        cursor = self._conn.cursor()
        inserted = 0
        try:
            cursor.execute(
                "SELECT restaurant_id FROM reservations WHERE id = %s LIMIT 1",
                (reservation_id,)
            )
            reservation_row = cursor.fetchone()
            restaurant_id = reservation_row[0] if reservation_row else None

            for item in items:
                name = item.get("item_name") or item.get("name")
                qty = int(item.get("quantity", item.get("qty", 1)) or 1)
                if not name:
                    continue
                if not restaurant_id:
                    continue
                cursor.execute(
                    "SELECT id FROM menu_item WHERE restaurant_id = %s AND LOWER(item_name) = LOWER(%s) LIMIT 1",
                    (restaurant_id, name)
                )
                menu_row = cursor.fetchone()
                if not menu_row:
                    continue
                item_id = menu_row[0]
                cursor.execute(
                    "INSERT INTO reservation_preorders (reservation_id, item_id, quantity) "
                    "VALUES (%s, %s, %s)",
                    (reservation_id, item_id, qty)
                )
                inserted += 1
            self._conn.commit()
            return inserted
        except Exception as e:
            self._conn.rollback()
            print(f"❌ Error inserting reservation preorders: {e}")
            return 0
        finally:
            cursor.close()