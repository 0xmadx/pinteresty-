from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import json
import uvicorn
from pathlib import Path

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Path to save the cookies
COOKIE_FILE = Path("pinterest_cookies.json")

@app.post("/update-cookie")
async def update_cookie(request: Request):
    data = await request.json()
    platform = data.get("platform")
    
    if platform == "pinterest":
        # The extension sends both a full cookie string and a JSON object
        cookie_string = data.get("cookie")
        cookie_json = data.get("cookie_json")
        
        # Save to file
        with open(COOKIE_FILE, "w") as f:
            json.dump({
                "cookie_string": cookie_string,
                "cookie_json": cookie_json
            }, f, indent=4)
            
        print(f"✅ Successfully updated Pinterest cookies! Saved to {COOKIE_FILE}")
        return {"status": "success", "message": "Pinterest cookies saved"}
        
    elif platform == "etsy":
        # Handle Etsy datadome cookie
        cookie_value = data.get("cookie")
        with open("etsy_datadome.txt", "w") as f:
            f.write(cookie_value)
        print("✅ Successfully updated Etsy datadome cookie!")
        return {"status": "success", "message": "Etsy cookie saved"}

if __name__ == "__main__":
    print("🚀 Starting local cookie server on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
