import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import ScraperConfig
from src.core.session_manager import SessionManager
from src.endpoints.manager import EndpointManager
from src.services.executor import EndpointExecutor

def run_test():
    print("Initializing Endpoint Engine for Search Grid Test...")
    config = ScraperConfig()
    session_manager = SessionManager(config)
    endpoint_manager = EndpointManager()
    executor = EndpointExecutor(session_manager, endpoint_manager)
    
    endpoint_name = "filter_new"
    print(f"[*] Executing {endpoint_name}...")
    
    try:
        # Executor automatically saves output to data/raw/
        executor.execute(endpoint_name)
        print(f"[+] Successfully executed {endpoint_name}. Check data/raw/ for output.")
    except Exception as e:
        print(f"[-] Error: {e}")

if __name__ == "__main__":
    run_test()
