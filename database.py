import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Tuple

class Database:
    def __init__(self, db_name: str = 'subscriptions.db'):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER PRIMARY KEY,
                subscription_ends TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add admin and banned users tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY,
                reason TEXT,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                banned_by INTEGER,
                FOREIGN KEY (banned_by) REFERENCES admins(user_id)
            )
        ''')
        
        # Create promo_codes table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS promo_codes (
                code TEXT PRIMARY KEY,
                days INTEGER NOT NULL,
                max_uses INTEGER NOT NULL,
                used_count INTEGER DEFAULT 0,
                created_by INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES admins(user_id)
            )
        ''')
        
        # Add some default admin users (replace with actual admin user IDs)
        default_admins = [
            (123456789, 'admin_username_1'),  # Replace with actual admin user ID and username
            (517892369, '@aircrouching')   # Add more admins as needed
        ]
        
        for user_id, username in default_admins:
            cursor.execute('''
                INSERT OR IGNORE INTO admins (user_id, username) VALUES (?, ?)
            ''', (user_id, username))
        
        self.conn.commit()

    def is_admin(self, user_id: int) -> bool:
        """Check if user is an admin"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM admins WHERE user_id = ?', (user_id,))
        return cursor.fetchone() is not None

    def is_banned(self, user_id: int) -> bool:
        """Check if user is banned"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT 1 FROM banned_users WHERE user_id = ?', (user_id,))
        return cursor.fetchone() is not None

    def ban_user(self, user_id: int, reason: str, admin_id: int) -> bool:
        """Ban a user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO banned_users (user_id, reason, banned_by)
                VALUES (?, ?, ?)
            ''', (user_id, reason, admin_id))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error banning user {user_id}: {e}")
            return False

    def unban_user(self, user_id: int) -> bool:
        """Unban a user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM banned_users WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error unbanning user {user_id}: {e}")
            return False

    def get_ban_info(self, user_id: int) -> Optional[dict]:
        """Get ban information for a user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT reason, banned_by, banned_at 
                FROM banned_users 
                WHERE user_id = ?
            ''', (user_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'reason': result[0],
                    'admin_id': result[1],
                    'banned_at': result[2]
                }
            return None
        except Exception as e:
            print(f"Error getting ban info for user {user_id}: {e}")
            return None

    def get_username(self, user_id: int) -> Optional[str]:
        """Get username by user ID"""
        try:
            cursor = self.conn.cursor()
            # Check in admins table first
            cursor.execute('SELECT username FROM admins WHERE user_id = ?', (user_id,))
            result = cursor.fetchone()
            if result and result[0]:
                return result[0]
            
            # If not found in admins, you might want to check users table if you have one
            # cursor.execute('SELECT username FROM users WHERE user_id = ?', (user_id,))
            # result = cursor.fetchone()
            # if result and result[0]:
            #     return result[0]
            
            return None
        except Exception as e:
            print(f"Error getting username for user {user_id}: {e}")
            return None

    def add_subscription(self, user_id: int, days: int) -> bool:
        """Add or update user subscription"""
        try:
            cursor = self.conn.cursor()
            now = datetime.now()
            
            # Check if user already has a subscription
            cursor.execute(
                'SELECT subscription_ends FROM subscriptions WHERE user_id = ?',
                (user_id,)
            )
            result = cursor.fetchone()
            
            if result and result[0] and datetime.fromisoformat(result[0]) > now:
                # Extend existing subscription
                new_end = datetime.fromisoformat(result[0]) + timedelta(days=days)
            else:
                # Create new subscription
                new_end = now + timedelta(days=days)
            
            cursor.execute('''
                INSERT OR REPLACE INTO subscriptions 
                (user_id, subscription_ends, updated_at)
                VALUES (?, ?, ?)
            ''', (user_id, new_end.isoformat(), now.isoformat()))
            
            self.conn.commit()
            return True
        except Exception as e:
            print(f"Error adding subscription for user {user_id}: {e}")
            return False

    def remove_subscription(self, user_id: int) -> bool:
        """Remove user's subscription"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            self.conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"Error removing subscription for user {user_id}: {e}")
            return False

    def get_subscription_status(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """Check if user has active subscription and return status text"""
        cursor = self.conn.cursor()
        cursor.execute(
            'SELECT subscription_ends FROM subscriptions WHERE user_id = ?',
            (user_id,)
        )
        result = cursor.fetchone()
        
        if not result or not result[0]:
            return False, "Истекла"
        
        end_date = datetime.fromisoformat(result[0])
        now = datetime.now()
        
        if end_date > now:
            # Format remaining time
            delta = end_date - now
            if delta.days > 30:
                months = delta.days // 30
                return True, f"Активна ({months} мес.)"
            elif delta.days > 0:
                return True, f"Активна ({delta.days} дн.)"
            elif delta.seconds >= 3600:  # More than 1 hour
                hours = delta.seconds // 3600
                return True, f"Активна ({hours} ч.)"
            else:
                minutes = delta.seconds // 60
                return True, f"Активна ({minutes} мин.)"
        return False, "Истекла"

    def create_promo_code(self, code: str, days: int, max_uses: int, created_by: int, expires_days: int = 30) -> bool:
        """Create a new promo code"""
        try:
            expires_at = datetime.now() + timedelta(days=expires_days)
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO promo_codes (code, days, max_uses, created_by, expires_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (code, days, max_uses, created_by, expires_at))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
        except Exception as e:
            print(f"Error creating promo code: {e}")
            return False

    def get_promo_code(self, code: str) -> Optional[dict]:
        """Get promo code details"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                SELECT code, days, max_uses, used_count, created_by, created_at, expires_at
                FROM promo_codes
                WHERE code = ? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
            ''', (code,))
            result = cursor.fetchone()
            if result:
                return {
                    'code': result[0],
                    'days': result[1],
                    'max_uses': result[2],
                    'used_count': result[3],
                    'created_by': result[4],
                    'created_at': result[5],
                    'expires_at': result[6]
                }
            return None
        except Exception as e:
            print(f"Error getting promo code: {e}")
            return None

    def use_promo_code(self, code: str, user_id: int) -> bool:
        """Use a promo code and apply subscription"""
        try:
            promo = self.get_promo_code(code)
            if not promo or promo['used_count'] >= promo['max_uses']:
                return False
            
            # Start a transaction
            self.conn.execute('BEGIN TRANSACTION')
            
            # Update promo code usage
            cursor = self.conn.cursor()
            cursor.execute('''
                UPDATE promo_codes
                SET used_count = used_count + 1
                WHERE code = ? AND used_count < max_uses
                RETURNING days
            ''', (code,))
            
            result = cursor.fetchone()
            if not result:
                self.conn.rollback()
                return False
                
            # Add subscription
            days = result[0]
            if not self.add_subscription(user_id, days):
                self.conn.rollback()
                return False
                
            self.conn.commit()
            return True
            
        except Exception as e:
            self.conn.rollback()
            print(f"Error using promo code: {e}")
            return False

    def delete_expired_promo_codes(self) -> int:
        """Delete expired promo codes and return count of deleted"""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                DELETE FROM promo_codes
                WHERE expires_at < CURRENT_TIMESTAMP
            ''')
            count = cursor.rowcount
            self.conn.commit()
            return count
        except Exception as e:
            print(f"Error deleting expired promo codes: {e}")
            return 0

# Singleton instance
db = Database()