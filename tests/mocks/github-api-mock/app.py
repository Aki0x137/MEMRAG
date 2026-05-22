"""GitHub API mock service for testing BYOD pipeline."""

from __future__ import annotations

import base64
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI()

# Synthetic repository structure for testing
SYNTHETIC_REPO = {
    "owner": "testorg",
    "repo": "test-repo",
    "branch": "main",
    "files": [
        {"name": "README.md", "path": "README.md", "size": 1024, "sha": "sha-readme-1"},
        {"name": "main.py", "path": "src/main.py", "size": 2048, "sha": "sha-main-1"},
        {"name": "utils.py", "path": "src/utils.py", "size": 512, "sha": "sha-utils-1"},
        {"name": "models.py", "path": "src/models.py", "size": 1536, "sha": "sha-models-1"},
        {"name": "api.py", "path": "src/api.py", "size": 2560, "sha": "sha-api-1"},
        {"name": "test_main.py", "path": "tests/test_main.py", "size": 1024, "sha": "sha-test-main-1"},
        {"name": "test_utils.py", "path": "tests/test_utils.py", "size": 768, "sha": "sha-test-utils-1"},
        {"name": "conftest.py", "path": "tests/conftest.py", "size": 512, "sha": "sha-conftest-1"},
        {"name": "config.yaml", "path": "config.yaml", "size": 256, "sha": "sha-config-1"},
        {"name": "requirements.txt", "path": "requirements.txt", "size": 128, "sha": "sha-requirements-1"},
    ]
}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/repos/{owner}/{repo}/branches/{branch}")
async def get_branch(owner: str, repo: str, branch: str):
    """Return branch info with commit SHA."""
    if owner != SYNTHETIC_REPO["owner"] or repo != SYNTHETIC_REPO["repo"]:
        raise HTTPException(status_code=404, detail="Repository not found")
    return {
        "name": branch,
        "commit": {
            "sha": "abc123def456",
            "url": f"https://api.github.com/repos/{owner}/{repo}/commits/abc123def456"
        }
    }


@app.get("/repos/{owner}/{repo}/git/trees/{sha}")
async def get_tree(owner: str, repo: str, sha: str, recursive: int = 0):
    """Return repository tree with synthetic files."""
    if owner != SYNTHETIC_REPO["owner"] or repo != SYNTHETIC_REPO["repo"]:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    tree = []
    for file_info in SYNTHETIC_REPO["files"]:
        tree.append({
            "path": file_info["path"],
            "mode": "100644",
            "type": "blob",
            "size": file_info["size"],
            "sha": file_info["sha"],
            "url": f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{file_info['sha']}"
        })
    
    return {
        "sha": sha,
        "url": f"https://api.github.com/repos/{owner}/{repo}/git/trees/{sha}",
        "tree": tree,
        "truncated": False
    }


@app.get("/repos/{owner}/{repo}/git/blobs/{sha}")
async def get_blob(owner: str, repo: str, sha: str):
    """Return file content (base64 encoded for binary, plain for text)."""
    if owner != SYNTHETIC_REPO["owner"] or repo != SYNTHETIC_REPO["repo"]:
        raise HTTPException(status_code=404, detail="Repository not found")
    
    # Find the file by SHA
    file_info = next((f for f in SYNTHETIC_REPO["files"] if f["sha"] == sha), None)
    if not file_info:
        raise HTTPException(status_code=404, detail="Blob not found")
    
    # Generate synthetic content based on file type
    if file_info["name"].endswith(".md"):
        content = f"# {file_info['name']}\n\nThis is a synthetic {file_info['name']} file for testing."
    elif file_info["name"].endswith(".py"):
        content = f'''"""Module: {file_info['name']}"""

def function_in_{file_info['name'].replace('.py', '').replace('-', '_')}():
    """Synthetic function for testing."""
    return "result from {file_info['name']}"

if __name__ == "__main__":
    print(function_in_{file_info['name'].replace('.py', '').replace('-', '_')}())
'''
    elif file_info["name"].endswith(".txt"):
        content = "# Synthetic requirements\ndependencies listed here\n"
    elif file_info["name"].endswith(".yaml"):
        content = "# Synthetic config\nversion: 1.0\nenvironment: test\n"
    else:
        content = f"Synthetic content for {file_info['name']}"
    
    # Encode as base64
    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    
    return {
        "sha": sha,
        "node_id": f"MDQ6QmxvYiB7ZmlsZV9zaGF9",
        "size": len(content),
        "url": f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{sha}",
        "content": encoded,
        "encoding": "base64"
    }


@app.get("/user")
async def get_user():
    """Return authenticated user info."""
    return {
        "login": "test-user",
        "id": 12345,
        "name": "Test User"
    }


@app.post("/repos/{owner}/{repo}/hooks/deliveries/poll")
async def webhook_poll(owner: str, repo: str):
    """Simulate webhook delivery (for future enhancement)."""
    return {"deliveries": []}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8085)
