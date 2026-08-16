import os
import requests
from dotenv import load_dotenv

class LLMClient:
    """
    Dedicated AI wrapper class for DeepSeek API.
    Enforces Separation of Responsibilities by decoupling LLM logic from Scraping logic.
    """
    def __init__(self):
        load_dotenv()
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.base_url = "https://api.deepseek.com/v1/chat/completions"
        self.model = "deepseek-chat"
        
    def analyze_sentiment(self, reviews_text):
        """
        Sends a batch of negative reviews to DeepSeek to summarize pain points.
        """
        if not self.api_key:
            return "WARNING: DEEPSEEK_API_KEY not found in .env file. Could not perform AI analysis."
            
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        system_prompt = (
            "You are an expert product analyst. Read the following negative customer reviews "
            "for an Etsy product. Identify and summarize the top 3 biggest pain points or flaws. "
            "Be extremely concise, formatting the output as a bulleted list of 3 items. "
            "Do not include introductory or concluding remarks."
        )
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Reviews:\n{reviews_text}"}
            ],
            "max_tokens": 300,
            "temperature": 0.3
        }
        
        try:
            response = requests.post(self.base_url, json=payload, headers=headers, timeout=15)
            if response.status_code == 200:
                data = response.json()
                return data['choices'][0]['message']['content'].strip()
            else:
                return f"Error: DeepSeek API returned status code {response.status_code}\n{response.text}"
        except Exception as e:
            return f"Error: Failed to communicate with DeepSeek API. {str(e)}"

    def classify_product_type(self, term):
        """digital / physical / personalized for a keyword, or None.

        The FALLBACK only — deterministic detection from page-one listings (D-22,
        `product_type.majority_type`) is tried first and is trusted over this. The LLM
        is reached only when that sample is split or thin, and even then this is
        CLASSIFICATION into a fixed set (D-27), never invention of a number. A verdict
        never rests on this without the operator seeing the basis was an LLM guess.

        Returns None on any uncertainty — an unparseable answer, a key that is missing,
        or a reply outside the three types — because a wrong type applies the wrong
        margin floor, and "I am not sure" must not silently become "physical".
        """
        if not self.api_key:
            return None

        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {self.api_key}"}
        system_prompt = (
            "Classify an Etsy search term into exactly one of: digital, physical, "
            "personalized. 'digital' = downloadable files (printables, SVGs, templates). "
            "'personalized' = physical goods customized per order (names, dates, photos). "
            "'physical' = ready-made physical goods. Reply with ONE word only, lowercase, "
            "from that set. If genuinely ambiguous, reply 'unknown'."
        )
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": f"Term: {term}"}],
            "max_tokens": 4,
            "temperature": 0.0,   # classification, not creativity
        }
        try:
            response = requests.post(self.base_url, json=payload, headers=headers, timeout=15)
            if response.status_code != 200:
                return None
            answer = response.json()["choices"][0]["message"]["content"].strip().lower()
            # Only a clean member of the set is trusted; anything else is uncertainty,
            # and uncertainty is None, never a defaulted type.
            return answer if answer in ("digital", "physical", "personalized") else None
        except Exception:
            return None
