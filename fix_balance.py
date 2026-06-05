import sqlite3, os

DB_PATH = os.getenv('DB_PATH', os.path.join(os.path.dirname(__file__), 'users.db'))
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

user = db.execute("SELECT * FROM users WHERE email='Sabitarman705@gmail.com'").fetchone()
if user:
    db.execute("UPDATE users SET balance=5.95 WHERE email='Sabitarman705@gmail.com'")
    db.commit()
    print(f"Done! {user['username']} balance = 5.95")
else:
    print("User not found. Login with Google first, then run again.")

db.close()
