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
