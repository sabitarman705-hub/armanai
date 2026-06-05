import sqlite3, os

DB_PATH = os.getenv('DB_PATH', os.path.join(os.path.dirname(__file__), 'users.db'))
db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row

row = db.execute("SELECT balance FROM users WHERE email='sabitarman705@gmail.com'").fetchone()
if row:
    print(f"Қазіргі баланс: ${row['balance']:.4f}")
    db.execute("UPDATE users SET balance = balance + 0.70 WHERE email='sabitarman705@gmail.com'")
    db.commit()
    row = db.execute("SELECT balance FROM users WHERE email='sabitarman705@gmail.com'").fetchone()
    print(f"Жаңа баланс: ${row['balance']:.4f}")
else:
    print("Пайдаланушы табылмады")
db.close()
