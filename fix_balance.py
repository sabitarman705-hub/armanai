import sqlite3, os

DB_PATH = os.getenv('DB_PATH', os.path.join(os.path.dirname(__file__), 'users.db'))
print(f"DB_PATH = {DB_PATH}")

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

users = db.execute("SELECT id, username, email, balance FROM users").fetchall()
print("Users in DB:")
for u in users:
    print(f"  id={u['id']} username={u['username']} email={u['email']} balance={u['balance']}")

db.execute("UPDATE users SET balance=10.0 WHERE email='sabitarman705@gmail.com'")
db.commit()
print("\nDone! Balance set to $10.00")
db.close()
