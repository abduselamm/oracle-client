from fastapi import APIRouter, Body, HTTPException, status, Response, Request
from typing import List, Dict, Any, Union
from database import get_db_connection, release_db_connection
import oracledb
import base64
import re
from datetime import datetime

router = APIRouter()

def parse_iso_dates(values):
    """Attempt to parse ISO string dates into datetime objects for safe DB binding."""
    for i, val in enumerate(values):
        if isinstance(val, str):
            if "T" in val and len(val) >= 19:
                try:
                    values[i] = datetime.fromisoformat(val.replace("Z", "+00:00"))
                except ValueError:
                    pass
            elif len(val) == 10 and val.count("-") == 2:
                try:
                    values[i] = datetime.strptime(val, "%Y-%m-%d")
                except ValueError:
                    pass
    return values
    
def handle_db_error(e, conn=None):
    """Unified error handling for database operations."""
    if conn:
        conn.rollback()
        
    if isinstance(e, oracledb.Error):
        error_obj = e.args[0]
        # Extract message and offset if it's an oracledb error object
        err_msg = getattr(error_obj, 'message', str(e))
        err_offset = getattr(error_obj, 'offset', None)
        
        detail = f"{err_msg}"
        if err_offset is not None:
             detail += f" (at offset {err_offset})"
        raise HTTPException(status_code=400, detail=detail)
    
    # Generic exception
    raise HTTPException(status_code=400, detail=str(e))

def row_to_dict(cursor, row):
    """Convert a row tuple to dictionary based on cursor description."""
    d = {}
    for idx, col in enumerate(cursor.description):
        val = row[idx]
        if hasattr(val, 'read'):
            try:
                val = val.read()
            except Exception:
                val = str(val)
        if isinstance(val, bytes):
            try:
                val = val.decode('utf-8')
            except UnicodeDecodeError:
                val = val.hex().upper()
        d[col[0]] = val
    return d

@router.post("/query", response_description="Execute raw SQL query", summary="Raw SQL Executor")
def execute_query(request: Request, body: Dict[str, Any] = Body(...)):
    """
    Execute a raw SQL query. Only accessible to QA users.
    Allows both SELECT and mutations (DELETE, UPDATE, etc.).
    """
    is_qa = getattr(request.state, "is_qa", False)
    if not is_qa:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Access Denied: SQL Worksheet is only available for QA environment."
        )

    sql = body.get("sql", "").strip()
    if not sql:
        raise HTTPException(status_code=400, detail="SQL query is required")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        
        # If the cursor has a description, it's a SELECT (or something returning rows)
        if cursor.description:
            rows = cursor.fetchall()
            return [row_to_dict(cursor, row) for row in rows]
        else:
            # It's a mutation (INSERT, UPDATE, DELETE, etc.)
            rowcount = cursor.rowcount
            conn.commit() # Ensure changes are persisted
            return {"status": "Success", "message": "Statement executed successfully.", "rowcount": rowcount}
            
    except Exception as e:
        handle_db_error(e, conn)
    finally:
        release_db_connection(conn)

@router.get("/_sys/tables", response_description="List all tables", summary="List tables", response_model=List[str])
def list_tables():
    """
    Retrieve a list of all existing table names in the current database user schema.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT table_name FROM user_tables")
        tables = [row[0] for row in cursor.fetchall()]
        return tables
    finally:
        release_db_connection(conn)

@router.post("/{table_name}/", response_description="Add new row(s)", summary="Create row(s) dynamically", response_model=Union[Dict[str, Any], List[Dict[str, Any]]])
def create_row(table_name: str, row: Union[Dict[str, Any], List[Dict[str, Any]]] = Body(...)):
    """
    Create new row(s) in the specified table.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        is_list = isinstance(row, list)
        docs = row if is_list else [row]
        
        if not docs:
            raise HTTPException(status_code=400, detail="Empty data provided")

        inserted_rows = []
        for doc in docs:
            columns = list(doc.keys())
            values = parse_iso_dates(list(doc.values()))
            
            # Handle potential SQL injection if table_name or columns are not sanitized. 
            # In a generic tool, we assume trusted schema names, but we should sanitize quotes.
            table_safe = table_name.replace('"', '')
            cols_safe = [c.replace('"', '') for c in columns]
            
            col_str = ", ".join(f'"{c}"' for c in cols_safe)
            bind_str = ", ".join(f":{i+1}" for i in range(len(values)))
            
            # Use ROWID to fetch the inserted row back
            sql = f'INSERT INTO "{table_safe}" ({col_str}) VALUES ({bind_str})'
            
            # Oracle doesn't have a simple returning rowid with executemany in all versions, 
            # so we iterate. 
            cursor.execute(sql, values)
            
            # Get the rowid of the inserted row
            cursor.execute(f"SELECT CHARTOROWID(:1) FROM DUAL", [cursor.lastrowid])
            rowid = cursor.fetchone()[0]
            
            cursor.execute(f'SELECT "{table_safe}".*, ROWIDTOCHAR(rowid) as "_id" FROM "{table_safe}" WHERE rowid = :1', [rowid])
            inserted_row = cursor.fetchone()
            inserted_rows.append(row_to_dict(cursor, inserted_row))
            
        conn.commit()
        return inserted_rows if is_list else inserted_rows[0]
    except Exception as e:
        handle_db_error(e, conn)
    finally:
        release_db_connection(conn)

@router.get("/{table_name}/", response_description="List all rows", summary="List rows", response_model=List[Dict[str, Any]])
def list_rows(table_name: str, skip: int = 0, limit: int = 0):
    """
    Retrieve rows in the table.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        table_safe = table_name.replace('"', '')
        
        sql = f'SELECT "{table_safe}".*, ROWIDTOCHAR(rowid) as "_id" FROM "{table_safe}"'
        
        if skip > 0 or limit > 0:
            sql += f" OFFSET {skip} ROWS"
            if limit > 0:
                sql += f" FETCH NEXT {limit} ROWS ONLY"
                
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        return [row_to_dict(cursor, row) for row in rows]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        release_db_connection(conn)

@router.get("/{table_name}/{id}", response_description="Get a single row", summary="Get row by ID", response_model=Dict[str, Any])
def show_row(table_name: str, id: str):
    """
    Retrieve a specific row by its ROWID masquerading as ID.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        table_safe = table_name.replace('"', '')
        
        cursor.execute(f'SELECT "{table_safe}".*, ROWIDTOCHAR(rowid) as "_id" FROM "{table_safe}" WHERE rowid = CHARTOROWID(:1)', [id])
        row = cursor.fetchone()
        
        if row is None:
            raise HTTPException(status_code=404, detail=f"Row {id} not found in {table_name}")
            
        return row_to_dict(cursor, row)
    except Exception as e:
        handle_db_error(e, conn)
    finally:
        release_db_connection(conn)

@router.patch("/{table_name}/{id}", response_description="Update a row", summary="Update row", response_model=Dict[str, Any])
def update_row(table_name: str, id: str, row: Dict[str, Any] = Body(...)):
    """
    Update an existing row by its ROWID.
    """
    if "_id" in row:
        del row["_id"]

    if not row:
        return show_row(table_name, id)

    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        table_safe = table_name.replace('"', '')
        
        columns = list(row.keys())
        values = parse_iso_dates(list(row.values()))
        
        set_clause = ", ".join([f'"{c}" = :{i+1}' for i, c in enumerate(columns)])
        values.append(id) # for the WHERE clause
        
        sql = f'UPDATE "{table_safe}" SET {set_clause} WHERE rowid = CHARTOROWID(:{len(values)})'
        cursor.execute(sql, values)
        
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Row {id} not found in {table_name}")
            
        conn.commit()
        
        return show_row(table_name, id)
    except Exception as e:
        handle_db_error(e, conn)
    finally:
        release_db_connection(conn)

@router.delete("/{table_name}/", response_description="Delete a table", summary="Delete table")
def delete_table(table_name: str):
    """
    Drop a table from the database.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        table_safe = table_name.replace('"', '')
        cursor.execute(f'DROP TABLE "{table_safe}" PURGE')
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        handle_db_error(e, conn)
    finally:
        release_db_connection(conn)

@router.delete("/{table_name}/rows", response_description="Delete all rows", summary="Delete all rows")
def delete_all_rows(table_name: str):
    """
    Delete all rows in a table.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        table_safe = table_name.replace('"', '')
        cursor.execute(f'TRUNCATE TABLE "{table_safe}"')
        # Maybe TRUNCATE doesn't return row count, so returning a simple success response
        return {"deleted": True}
    except Exception as e:
        handle_db_error(e, conn)
    finally:
        release_db_connection(conn)

@router.delete("/{table_name}/{id}", response_description="Delete a row", summary="Delete row")
def delete_row(table_name: str, id: str):
    """
    Remove a row from the table by its ROWID.
    """
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        table_safe = table_name.replace('"', '')
        
        cursor.execute(f'DELETE FROM "{table_safe}" WHERE rowid = CHARTOROWID(:1)', [id])
        
        if cursor.rowcount == 0:
             raise HTTPException(status_code=404, detail=f"Row {id} not found in {table_name}")
             
        conn.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        handle_db_error(e, conn)
    finally:
        release_db_connection(conn)
