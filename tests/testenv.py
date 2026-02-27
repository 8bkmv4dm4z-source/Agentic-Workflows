# env_test.py
from dotenv import load_dotenv
import os

load_dotenv()
print("Loaded:", bool(os.getenv("GROQ_API_KEY")))