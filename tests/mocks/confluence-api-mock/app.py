"""Confluence API mock service with OAuth 2.0 3-LO flow for testing."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

app = FastAPI()

# Store for OAuth tokens and sessions
OAUTH_SESSIONS: dict[str, dict] = {}
ACCESS_TOKENS: dict[str, dict] = {}

# Synthetic pages
SYNTHETIC_PAGES = [
    {
        "id": "page-001",
        "title": "Getting Started with MEMRAG",
        "space": "ENG",
        "content": "# Getting Started\n\nMEMRAG is a production memory and RAG platform.",
        "lastModified": "2026-05-20T10:00:00Z"
    },
    {
        "id": "page-002",
        "title": "Architecture Overview",
        "space": "ARCH",
        "content": "<h2>System Architecture</h2><p>Four-layer recall system with Temporal orchestration.</p>",
        "lastModified": "2026-05-19T14:30:00Z"
    },
    {
        "id": "page-003",
        "title": "API Design",
        "space": "ENG",
        "content": "<h2>REST API Endpoints</h2><ul><li>POST /v1/connectors</li><li>GET /v1/connectors/{id}</li></ul>",
        "lastModified": "2026-05-18T09:15:00Z"
    },
    {
        "id": "page-004",
        "title": "Deployment Guide",
        "space": "OPS",
        "content": "# Deployment\n\n1. Configure environment\n2. Run migrations\n3. Start services",
        "lastModified": "2026-05-17T16:45:00Z"
    },
    {
        "id": "page-005",
        "title": "Integration Testing",
        "space": "QA",
        "content": "# Testing Strategy\n\nFull end-to-end testing for all phases.",
        "lastModified": "2026-05-16T11:20:00Z"
    },
]


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/oauth/authorize")
async def oauth_authorize(
    client_id: str = Query(...),
    redirect_uri: str = Query(...),
    state: str = Query(...),
):
    """OAuth 2.0 authorization endpoint (step 1)."""
    # Store the session
    session_id = str(uuid.uuid4())
    OAUTH_SESSIONS[session_id] = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    
    # For mock, auto-approve and redirect back
    auth_code = str(uuid.uuid4())
    return RedirectResponse(
        url=f"{redirect_uri}?code={auth_code}&state={state}",
        status_code=302
    )


@app.post("/oauth/token")
async def oauth_token(request: Request):
    """OAuth 2.0 token endpoint (step 2 & 3)."""
    # Parse form data
    form_data = await request.form()
    grant_type = form_data.get("grant_type")
    code = form_data.get("code")
    refresh_token = form_data.get("refresh_token")
    
    if grant_type == "authorization_code":
        # Exchange authorization code for access token
        access_token = str(uuid.uuid4())
        refresh_tok = str(uuid.uuid4())
        
        ACCESS_TOKENS[access_token] = {
            "user_id": "test-user",
            "expires_in": 3600,
        }
        
        return {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": refresh_tok,
        }
    
    elif grant_type == "refresh_token":
        # Refresh the access token
        if not refresh_token:
            raise HTTPException(status_code=400, detail="refresh_token required")
        
        new_access_token = str(uuid.uuid4())
        ACCESS_TOKENS[new_access_token] = {
            "user_id": "test-user",
            "expires_in": 3600,
        }
        
        return {
            "access_token": new_access_token,
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": refresh_token,
        }
    
    else:
        raise HTTPException(status_code=400, detail="Unsupported grant_type")


@app.get("/wiki/rest/api/user/current")
async def get_current_user(request: Request):
    """Validate access token by fetching current user."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "") if "Bearer" in auth_header else auth_header
    if token not in ACCESS_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return {
        "type": "known",
        "username": "test-user",
        "userKey": "test-user-key",
        "name": "Test User",
        "email": "test@example.com",
    }


@app.get("/wiki/rest/api/content/search")
async def search_content(
    cql: str = Query(...),
    limit: int = Query(100),
    expand: str = Query(""),
    request: Request = None,
):
    """CQL search for pages in specified spaces."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "") if "Bearer" in auth_header else auth_header
    if token not in ACCESS_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # Parse space filter from CQL (simplified)
    # Expected format: "space IN (ENG,ARCH,...)"
    spaces = []
    if "space IN" in cql:
        start = cql.find("(") + 1
        end = cql.find(")")
        spaces_str = cql[start:end]
        spaces = [s.strip() for s in spaces_str.split(",")]
    
    # Filter pages by space
    results = []
    for page in SYNTHETIC_PAGES:
        if not spaces or page["space"] in spaces:
            results.append({
                "id": page["id"],
                "type": "page",
                "title": page["title"],
                "space": {"key": page["space"]},
                "version": {"when": page["lastModified"]},
                "_links": {
                    "self": f"https://confluence.example.com/wiki/spaces/{page['space']}/pages/{page['id']}",
                    "webui": f"/wiki/spaces/{page['space']}/pages/{page['id']}"
                }
            })
    
    return {
        "results": results[:limit],
        "start": 0,
        "limit": limit,
        "size": len(results),
        "totalSize": len(results),
    }


@app.get("/wiki/rest/api/content/{page_id}")
async def get_page_content(
    page_id: str,
    expand: str = Query(""),
    authorization: str = ...,
):
    """Fetch page content."""
    token = authorization.replace("Bearer ", "") if "Bearer" in authorization else authorization
    if token not in ACCESS_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    page = next((p for p in SYNTHETIC_PAGES if p["id"] == page_id), None)
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    
    # Return HTML or raw content based on expand parameter
    body_storage = {
        "value": f"<h1>{page['title']}</h1>\n{page['content']}",
        "representation": "storage"
    }
    
    return {
        "id": page["id"],
        "type": "page",
        "title": page["title"],
        "space": {"key": page["space"]},
        "body": {"storage": body_storage} if "body.storage" in expand else {},
        "version": {"when": page["lastModified"]},
        "_links": {
            "self": f"https://confluence.example.com/api/content/{page_id}",
            "webui": f"/wiki/spaces/{page['space']}/pages/{page_id}"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8084)
