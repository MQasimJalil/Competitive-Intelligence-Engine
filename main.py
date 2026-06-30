import psycopg2
from dotenv import load_dotenv
import os
import sys

# Load environment variables from .env
load_dotenv()

# Fetch variables
DATABASE_URL = os.getenv("DATABASE_URL")
print("Attempting to connect to database using URL...")
if DATABASE_URL:
    try:
        # Hide credentials in printout
        host_part = DATABASE_URL.split("@")[-1]
        print(f"Target Database Host: {host_part}")
    except Exception:
        print("Target Database Host: (Invalid URL format)")
else:
    print("DATABASE_URL is not defined in .env")
    sys.exit(1)

try:
    # Connect to the database
    connection = psycopg2.connect(DATABASE_URL)
    print("SUCCESS: Connected to the database successfully!")
    cursor = connection.cursor()
    cursor.execute("SELECT version();")
    print("Database Version:", cursor.fetchone()[0])
    connection.close()
except Exception as e:
    print("\nERROR: Connection failed!", file=sys.stderr)
    print(e, file=sys.stderr)
    print("\nTroubleshooting Advice:", file=sys.stderr)
    print("- If the error is 'Network is unreachable', this environment does not support IPv6 routing.", file=sys.stderr)
    print("  Use the Supabase Connection Pooler (port 5432/6543) instead of direct connection.", file=sys.stderr)
    print("- If the error is 'tenant/user ... not found', you must toggle on 'Enable Connection Pooler'", file=sys.stderr)
    print("  under Settings -> Database in your Supabase Dashboard.", file=sys.stderr)
    sys.exit(1)
