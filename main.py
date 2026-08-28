import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from dataset_manager.scripts.cli import app

if __name__ == "__main__":
    app()
