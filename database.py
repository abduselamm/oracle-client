import os
import hvac
import oracledb
from dotenv import load_dotenv

load_dotenv()

def get_all_secrets():
    """Fetches all secrets from Vault once and returns them as a dict."""
    vault_addr = os.environ.get("VAULT_ADDR")
    vault_token = os.environ.get("VAULT_TOKEN")
    vault_path = os.environ.get("VAULT_PATH")

    if vault_addr and vault_token and vault_path:
        try:
            client = hvac.Client(url=vault_addr, token=vault_token)
            if client.is_authenticated():
                parts = vault_path.strip("/").split("/", 1)
                mount_point = parts[0]
                secret_path = parts[1] if len(parts) > 1 else ""
                
                try:
                    read_response = client.secrets.kv.v2.read_secret_version(mount_point=mount_point, path=secret_path)
                    secrets = read_response['data']['data']
                except Exception:
                    read_response = client.read(vault_path)
                    secrets = read_response['data'] if (read_response and 'data' in read_response) else {}

                if isinstance(secrets, dict) and "data" in secrets and "metadata" in secrets:
                    secrets = secrets["data"]
                
                return secrets
        except Exception as e:
            print(f"Vault error during bulk fetch: {e}")
    return {}

# Load everything
VAULT_SECRETS = get_all_secrets()

# 1. Oracle Connection String
def resolve_oracle_conn_string(secrets):
    for key in ["ORACLE_CONNECTION_STRING", "ORACLE_URI", "ORACLE_URL"]:
        if key in secrets:
            print(f"Vault: Found {key} in secret.")
            return secrets[key]
    return os.environ.get("ORACLE_CONNECTION_STRING") or os.environ.get("ORACLE_URI") or \
           os.environ.get("ORACLE_URL") or "system/oracle@localhost:1521/XEPDB1"

# 2. API Key
def resolve_api_key(secrets):
    if "API_KEY" in secrets:
        print(f"Vault: Found API_KEY in secret.")
        return secrets["API_KEY"]
    return os.environ.get("API_KEY")

# 3. Root Path
def resolve_root_path(secrets):
    return "/api/v1/oracle-client"

ORACLE_CONN_STRING = resolve_oracle_conn_string(VAULT_SECRETS)
VALID_API_KEY = resolve_api_key(VAULT_SECRETS)
APP_ROOT_PATH = resolve_root_path(VAULT_SECRETS)

# Establish connection pool using oracledb
try:
    if ORACLE_CONN_STRING:
        # We can create a simple connection pool or function to get connection
        # to ensure thread-safety for FastAPI
        pool = oracledb.create_pool(dsn=ORACLE_CONN_STRING, min=2, max=10, increment=1)
        print(f"Oracle: Connection pool initialized successfully.")
    else:
        pool = None
        print(f"Oracle: Connection string empty, pool not initialized.")
except Exception as e:
    pool = None
    print(f"Oracle: Failed to initialize connection pool: {e}")

def get_db_connection():
    if not pool:
        raise Exception("Database connection pool is not initialized")
    return pool.acquire()

def release_db_connection(conn):
    if pool and conn:
        pool.release(conn)
