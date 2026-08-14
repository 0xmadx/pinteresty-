package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/go-redis/redis/v8"
)

var ctx = context.Background()
var rdb *redis.Client

// Extract the required API Key from ENV, default to a secure dummy one if none provided
var apiKey = os.Getenv("API_KEY")

func init() {
	if apiKey == "" {
		apiKey = "super_secret_key_123" // Default for testing; override in docker-compose
		log.Println("WARNING: API_KEY not set in environment. Using default key for development.")
	}

	redisURL := os.Getenv("REDIS_URL")
	if redisURL == "" {
		redisURL = "redis://localhost:6379/0"
	}

	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		log.Fatalf("Error parsing REDIS_URL: %v", err)
	}

	rdb = redis.NewClient(opt)
}

// Payload matches the JSON payload sent by the Chrome extension
type Payload struct {
	Platform   string      `json:"platform"`
	ProfileID  string      `json:"profile_id"`
	CookieJSON interface{} `json:"cookie_json"`
	ShopID     string      `json:"shop_id"`
	CSRFToken  string      `json:"csrf_token"`
}

func authMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Set CORS headers for all requests
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		
		// Allow OPTIONS preflight request to succeed without auth
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}

		// Expecting "Authorization: Bearer <API_KEY>"
		authHeader := r.Header.Get("Authorization")
		if authHeader == "" {
			http.Error(w, `{"error": "Unauthorized: Missing Authorization header"}`, http.StatusUnauthorized)
			return
		}

		parts := strings.SplitN(authHeader, " ", 2)
		if len(parts) != 2 || parts[0] != "Bearer" || parts[1] != apiKey {
			http.Error(w, `{"error": "Unauthorized: Invalid API Key"}`, http.StatusUnauthorized)
			return
		}

		next(w, r)
	}
}

func updateCookieHandler(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	if r.Method != "POST" {
		http.Error(w, `{"error": "Method Not Allowed"}`, http.StatusMethodNotAllowed)
		return
	}

	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, `{"error": "Failed to read body"}`, http.StatusBadRequest)
		return
	}
	defer r.Body.Close()

	var p Payload
	if err := json.Unmarshal(body, &p); err != nil {
		http.Error(w, `{"error": "Invalid JSON format"}`, http.StatusBadRequest)
		return
	}

	if p.Platform == "" {
		p.Platform = "etsy"
	}
	if p.ProfileID == "" {
		p.ProfileID = "default"
	}

	cookieStr := ""
	if p.CookieJSON != nil {
		b, _ := json.Marshal(p.CookieJSON)
		cookieStr = string(b)
	}

	key := fmt.Sprintf("cookie:%s:%s", p.Platform, p.ProfileID)
	
	// Create mapping for Redis Hash
	mapping := map[string]interface{}{
		"is_valid": "1",
		"last_updated": time.Now().Unix(),
	}

	if p.Platform == "etsy" || p.Platform == "pinterest" {
		if cookieStr == "" {
			http.Error(w, `{"error": "Missing cookie_json value"}`, http.StatusBadRequest)
			return
		}
		mapping["cookies_json"] = cookieStr
		log.Printf("🔄 [Go Server] Received %s cookies from profile '%s'! Updating Redis...\n", p.Platform, p.ProfileID)
	} else if p.Platform == "etsy_private" {
		if cookieStr != "" {
			mapping["cookies_json"] = cookieStr
		}
		if p.CSRFToken != "" {
			mapping["csrf_token"] = p.CSRFToken
		}
		if p.ShopID != "" {
			mapping["shop_id"] = p.ShopID
		}
		log.Printf("🔄 [Go Server] Received Etsy Private data from profile '%s'! Updating Redis...\n", p.ProfileID)
	} else {
		http.Error(w, fmt.Sprintf(`{"error": "Unknown platform: %s"}`, p.Platform), http.StatusBadRequest)
		return
	}

	// 1. HSET the cookie mapping
	err = rdb.HSet(ctx, key, mapping).Err()
	if err != nil {
		log.Printf("Redis HSET error: %v\n", err)
		http.Error(w, `{"error": "Failed to save to Redis"}`, http.StatusInternalServerError)
		return
	}

	// 2. SADD the profile_id to the valid pool
	err = rdb.SAdd(ctx, fmt.Sprintf("valid_profiles:%s", p.Platform), p.ProfileID).Err()
	if err != nil {
		log.Printf("Redis SADD error: %v\n", err)
		http.Error(w, `{"error": "Failed to save to Redis"}`, http.StatusInternalServerError)
		return
	}

	w.WriteHeader(http.StatusOK)
	w.Write([]byte(fmt.Sprintf(`{"status": "success", "message": "%s data synced to Redis via Go"}`, p.Platform)))
}

func main() {
	http.HandleFunc("/update-cookie", authMiddleware(updateCookieHandler))

	port := os.Getenv("PORT")
	if port == "" {
		port = "8000"
	}

	log.Printf("🚀 Starting High-Performance Go Cookie Sync Server on port %s", port)
	log.Printf("Waiting for Chrome Extensions to beam cookies...")
	log.Fatal(http.ListenAndServe(":"+port, nil))
}
