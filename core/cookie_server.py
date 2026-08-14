from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import json
from core.cookie_vault import RedisCookieVault
from core.settings import ScraperConfig

app = FastAPI(title="DataDome & Pinterest Cookie Syncer (Redis)")

# Allow Chrome Extension to POST to this server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In a real app, restrict to chrome-extension:// origins
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

config = ScraperConfig()
vault = RedisCookieVault(config)

@app.post("/update-cookie")
async def update_cookie(request: Request):
    data = await request.json()
    platform = data.get("platform", "etsy")
    profile_id = data.get("profile_id", "default")
    
    if platform == "etsy":
        cookie_json = data.get("cookie_json")
        if not cookie_json:
            raise HTTPException(status_code=400, detail="Missing cookie_json value")
            
        print(f"🔄 [Server] Received Etsy cookies from profile '{profile_id}'! Updating Redis...")
        vault.upsert_account(platform="etsy", profile_id=profile_id, cookie_json=cookie_json)
        return {"status": "success", "message": "Etsy cookie synced to Redis"}
        
    elif platform == "etsy_private":
        shop_id = data.get("shop_id")
        csrf_token = data.get("csrf_token")
        
        print(f"🔄 [Server] Received Etsy Private tokens from profile '{profile_id}'! Updating Redis...")
        vault.upsert_account(platform="etsy_private", profile_id=profile_id, cookie_json=None, csrf_token=csrf_token, shop_id=shop_id)
        return {"status": "success", "message": "Etsy Private tokens synced to Redis"}
        
    elif platform == "pinterest":
        cookie_json = data.get("cookie_json")
        if not cookie_json:
            raise HTTPException(status_code=400, detail="Missing cookie_json value")
            
        print(f"🔄 [Server] Received Pinterest cookie from profile '{profile_id}'! Updating Redis...")
        vault.upsert_account(platform="pinterest", profile_id=profile_id, cookie_json=cookie_json)
        return {"status": "success", "message": "Pinterest cookie synced to Redis"}
        
    else:
        raise HTTPException(status_code=400, detail=f"Unknown platform: {platform}")

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Redis Cookie Sync Server on http://localhost:8000")
    print("Waiting for Chrome Extensions to beam cookies...")
    uvicorn.run(app, host="127.0.0.1", port=8000)
