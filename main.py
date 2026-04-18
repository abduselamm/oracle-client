from fastapi import FastAPI, Depends, HTTPException, Security, status
from fastapi.security.api_key import APIKeyHeader
from routes.dynamic import router as dynamic_router
from database import VALID_API_KEY, QA_API_KEY, UAT_API_KEY, APP_ROOT_PATH, ORACLE_CONN_STRING, pool
from fastapi import Request

API_KEY_NAME = "X-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(request: Request, api_key_header: str = Security(api_key_header)):
    # Debug logging
    incoming_key = api_key_header if api_key_header else "MISSING"
    
    safe_incoming = str(api_key_header).strip() if api_key_header else ""
    safe_valid = str(VALID_API_KEY).strip() if VALID_API_KEY else ""
    safe_qa = str(QA_API_KEY).strip() if QA_API_KEY else ""
    safe_uat = str(UAT_API_KEY).strip() if UAT_API_KEY else ""
    
    is_admin = (safe_incoming == safe_valid and safe_valid != "")
    is_qa = (safe_incoming == safe_qa and safe_qa != "")
    is_uat = (safe_incoming == safe_uat and safe_uat != "")

    print(f"Auth check: incoming={safe_incoming[:4]}... matches admin={is_admin}, matches qa={is_qa}, matches uat={is_uat}")

    if is_admin:
        print("Auth: Matches ADMIN key.")
        request.state.read_only = False
        return api_key_header
    
    if is_qa or is_uat:
        env_name = "QA" if is_qa else "UAT"
        print(f"Auth: Matches {env_name} key. Setting read_only=True")
        # Allow POST to /query endpoint specifically for the worksheet
        is_query_path = request.url.path.endswith("/query")
        
        if request.method not in ["GET", "OPTIONS"] and not is_query_path:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Read-Only access: Mutation not allowed on {env_name} environment",
            )
        request.state.read_only = True
        request.state.is_qa = is_qa
        request.state.is_uat = is_uat
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
print(f"UAT_API_KEY: {'[SET]' if UAT_API_KEY else 'NOT SET'}")
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
    is_qa = getattr(request.state, "is_qa", False)
    is_uat = getattr(request.state, "is_uat", False)
    print(f"DEBUG: /info called. read_only={read_only}, is_qa={is_qa}, is_uat={is_uat}")
    return {
        "read_only": read_only,
        "is_qa": is_qa,
        "is_uat": is_uat,
        "env": "QA" if is_qa else ("UAT" if is_uat else "PROD/DEV")
    }

@app.get("/", tags=["Root"])
async def read_root():
    return {
        "message": "Welcome to the Oracle Client API!", 
        "root_path": PREFIX,
        "docs": f"{PREFIX}/docs" if PREFIX else "/docs"
    }
