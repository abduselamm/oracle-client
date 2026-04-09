from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from routes.dynamic import router as dynamic_router
from database import VALID_API_KEY, QA_API_KEY, APP_ROOT_PATH, ORACLE_CONN_STRING, pool
from fastapi import Request

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(request: Request, api_key_header: str = Security(api_key_header)):
    # Debug logging
    incoming_key = api_key_header if api_key_header else "MISSING"
    
    safe_incoming = str(api_key_header).strip() if api_key_header else ""
    safe_valid = str(VALID_API_KEY).strip() if VALID_API_KEY else ""
    safe_qa = str(QA_API_KEY).strip() if QA_API_KEY else ""
    
    is_admin = (safe_incoming == safe_valid and safe_valid != "")
    is_qa = (safe_incoming == safe_qa and safe_qa != "")

    print(f"Auth check: incoming={safe_incoming[:4]}... matches admin={is_admin}, matches qa={is_qa}")

    if is_admin:
        print("Auth: Matches ADMIN key.")
        request.state.read_only = False
        return api_key_header
    
    if is_qa:
        print("Auth: Matches QA key. Setting read_only=True")
        # Check if the method is permitted
        if request.method not in ["GET", "OPTIONS"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Read-Only access: Mutation not allowed on QA environment",
            )
        request.state.read_only = True
        return api_key_header

    # If neither matches
    print("--- DEBUG AUTH MISMATCH ---")
    print(f"Raw Incoming: {repr(api_key_header)}")
    print("---------------------------")
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API Key",
    )

# Handle potential trailing/leading slashes for prefix
PREFIX = APP_ROOT_PATH.rstrip("/")
if PREFIX and not PREFIX.startswith("/"):
    PREFIX = "/" + PREFIX

# Log configuration on module load
print(f"--- Configuration ---")
print(f"ORACLE_URI: {'[HIDDEN]' if ORACLE_CONN_STRING else 'NOT SET'}")
print(f"ADMIN_API_KEY: {'[SET]' if VALID_API_KEY else 'NOT SET'}")
print(f"QA_API_KEY: {'[SET]' if QA_API_KEY else 'NOT SET'}")
print(f"APP_ROOT_PATH: '{APP_ROOT_PATH}'")
print(f"Computed PREFIX: '{PREFIX}'")
print(f"---------------------")

app = FastAPI(
    title="Oracle Client API",
    # We use explicit prefixes for rowation to ensure it works even if root_path logic fails
    openapi_url=f"{PREFIX}/openapi.json" if PREFIX else "/openapi.json",
    docs_url=f"{PREFIX}/docs" if PREFIX else "/docs",
    redoc_url=f"{PREFIX}/redoc" if PREFIX else "/redoc",
    description="""
A generic RESTful API using FastAPI and Oracle Database.

## Features

- **Authentication**: API Key protection via `X-API-KEY` header.
- **Dynamic Routes**: managing any table.
- **Docker**: support for easy deployment.
    """,
    version="1.0.0"
)

# CORS Configuration
from fastapi.middleware.cors import CORSMiddleware
origins = ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# if the proxy hits the full path but doesn't strip it.
app.include_router(
    dynamic_router, 
    prefix=PREFIX, 
    tags=["dynamic"], 
    dependencies=[Depends(get_api_key)]
)

@app.on_event("startup")
async def startup_db_client():
    if pool:
        print(f"Oracle: Connection pool is ready.")
    else:
        print(f"Oracle: Warning! Connection pool is NOT ready.")

@app.get(f"{PREFIX}/info", tags=["Root"])
async def get_info(request: Request, _ = Depends(get_api_key)):
    read_only = getattr(request.state, "read_only", False)
    print(f"DEBUG: /info called. read_only={read_only}")
    return {
        "read_only": read_only,
        "env": "QA" if read_only else "PROD/DEV"
    }

@app.get("/", tags=["Root"])
async def read_root():
    return {
        "message": "Welcome to the Oracle Client API!", 
        "root_path": PREFIX,
        "docs": f"{PREFIX}/docs" if PREFIX else "/docs"
    }
