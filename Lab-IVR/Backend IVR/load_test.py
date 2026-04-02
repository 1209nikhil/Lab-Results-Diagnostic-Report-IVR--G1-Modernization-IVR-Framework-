import requests
import time
import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = os.getenv("BASE_URL")

def load_test(num_requests=20):
    if not BASE_URL:
        print("Please set BASE_URL in your .env file before running the load test.")
        return

    # Targeting the starting point of our IVR
    url = f"{BASE_URL}/voice"
    payload = {"CallSid": "loadtest-001"}
    
    print(f"Starting load test on {url} with {num_requests} requests...")
    
    start_time = time.time()
    success = 0
    errors = 0
    
    for i in range(num_requests):
        try:
            # Twilio hits endpoints with POST and Form data
            res = requests.post(url, data=payload)
            if res.status_code == 200 or res.status_code == 204:
                success += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1
            
    total_time = time.time() - start_time
    
    print("\n--- Load Test Results ---")
    print(f"Sent {num_requests} requests")
    print(f"Successful: {success}")
    print(f"Failed: {errors}")
    print(f"Total Time: {total_time:.2f} seconds")
    if num_requests > 0:
        print(f"Average response time: {total_time / num_requests:.3f} seconds per request")

if __name__ == "__main__":
    load_test(50)
