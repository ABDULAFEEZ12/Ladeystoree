from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

# 🔑 Your MongoDB connection string
uri = "mongodb+srv://ladeyuser:ladey123@cluster0.nqyjnam.mongodb.net/ladeystoree?retryWrites=true&w=majority"

# Create client
client = MongoClient(uri, server_api=ServerApi('1'))

try:
    # Test connection
    client.admin.command('ping')
    print("✅ Connected to MongoDB!")

    # Use database
    db = client["ladeystoree"]

    # Insert test data
    db.users.insert_one({"name": "Afeez", "status": "testing"})

    # Fetch test data
    user = db.users.find_one({"name": "Afeez"})
    print("📦 Data from DB:", user)

except Exception as e:
    print("❌ Error:", e)