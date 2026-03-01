import bcrypt
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
db = client["kikky"]

email = "admin@email.com"
password = "yourpassword"

hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt())

db["admins"].insert_one({
    "email": email,
    "password": hashed_password
})

print("Admin created successfully.")
print("Loaded URI:", os.getenv("MONGO_URI"))