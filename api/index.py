import os
import sys

os.environ["HOME"] = "/tmp"
os.environ["CREWAI_STORAGE_DIR"] = "/tmp/crewai"

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app

handler = app
