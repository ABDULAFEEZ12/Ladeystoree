import bcrypt
from pymongo import MongoClient
import certifi
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"), tlsCAFile=certifi.where())
db = client["ladeystoree"]
admins = db["admins"]

email = "admin@ladeystoree.com"
password = "admin123"

# Delete old admin if exists
admins.delete_one({"email": email})

# Create new admin
hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
admins.insert_one({
    "email": email,
    "password": hashed,
    "role": "superadmin"
})

print("=" * 50)
print("✅ ADMIN CREATED!")
print("=" * 50)
print(f"📧 Email:    {email}")
print(f"🔑 Password: {password}")
print("=" * 50)
print("\n🔗 Login at: http://127.0.0.1:5000/admin/login")