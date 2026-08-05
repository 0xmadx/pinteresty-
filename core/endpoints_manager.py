import json
import re
import shlex
from typing import Dict, Any

class EndpointManager:
    def __init__(self, registry_path: str = "inputs/registry.json"):
        self.registry_path = registry_path
        self.endpoints = self._load_registry()

    def _load_registry(self) -> Dict[str, Any]:
        try:
            with open(self.registry_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("endpoints", {})
        except FileNotFoundError:
            return {}

    def _save_registry(self):
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump({"endpoints": self.endpoints}, f, indent=4)

    def get_endpoint(self, name: str) -> Dict[str, Any]:
        if name not in self.endpoints:
            raise ValueError(f"Endpoint '{name}' not found in registry.")
        return self.endpoints[name]

    def parse_curl_command(self, name: str, curl_string: str) -> None:
        """
        Takes a raw 'copy as cURL (bash)' string and parses it into the registry.
        """
        # Very basic naive parser for typical curl bash exports
        parts = shlex.split(curl_string)
        
        url = ""
        method = "GET"
        headers = {}
        cookies = {}
        data = None
        
        it = iter(parts)
        for part in it:
            if part == "curl":
                continue
            elif part.startswith("http"):
                url = part
            elif part == "-H" or part == "--header":
                header_str = next(it)
                if ":" in header_str:
                    k, v = header_str.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if k.lower() == "cookie":
                        # Parse cookie string into dict
                        for c_item in v.split(";"):
                            if "=" in c_item:
                                c_k, c_v = c_item.split("=", 1)
                                cookies[c_k.strip()] = c_v.strip()
                    else:
                        headers[k] = v
            elif part == "-b" or part == "--cookie":
                cookie_str = next(it)
                for c_item in cookie_str.split(";"):
                    if "=" in c_item:
                        c_k, c_v = c_item.split("=", 1)
                        cookies[c_k.strip()] = c_v.strip()
            elif part == "--data-raw" or part == "--data":
                data = next(it)
                method = "POST"
            elif part == "-X" or part == "--request":
                method = next(it).upper()
                
        self.endpoints[name] = {
            "method": method,
            "url_template": url,
            "headers": headers,
            "cookies": cookies
        }
        if data:
            self.endpoints[name]["payload_template"] = data
            
        self._save_registry()
        print(f"Successfully registered endpoint: {name}")
