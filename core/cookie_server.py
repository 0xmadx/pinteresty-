from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import dotenv
import os
from pathlib import Path

app = FastAPI(title="Etsy DataDome Syncer")

# Allow Chrome Extension to POST to this server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In a real app, restrict to chrome-extension:// origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CookiePayload(BaseModel):
    cookie: str

@app.post("/update-cookie")
async def update_cookie(payload: CookiePayload):
    if not payload.cookie:
        raise HTTPException(status_code=400, detail="Missing cookie value")
        
    env_path = Path(".env")
    if not env_path.exists():
        env_path.touch()
        
    print(f"🔄 Received new DataDome cookie from Chrome Extension! Updating .env...")
    
    # Update the .env file programmatically
    dotenv.set_key(env_path, "DATADOME_COOKIE", payload.cookie)
    
    print("✅ Successfully updated DATADOME_COOKIE in .env")
    return {"status": "success", "message": "Cookie synced"}

if __name__ == "__main__":
    import uvicorn
    # Run the server on port 8000
    print("🚀 Starting Cookie Sync Server on http://localhost:8000")
    print("Waiting for Chrome Extension to beam cookies...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
