import os

# Use HF Mirror - MUST BE SET BEFORE IMPORTS
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

import ssl
import warnings
from pathlib import Path
from sentence_transformers import SentenceTransformer

# Suppress warnings
warnings.filterwarnings("ignore")

def download_model():
    """
    Download the model locally, bypassing SSL verification if necessary.
    """
    model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    
     # Define target directory
    
    # Define target directory
    # We want it in /backend/data/models
    # valid relative to this script: ../../data/models/paraphrase-multilingual-MiniLM-L12-v2
    
    script_dir = Path(__file__).parent.absolute()
    base_dir = script_dir.parent  # backend
    models_dir = base_dir / "data" / "models" / "paraphrase-multilingual-MiniLM-L12-v2"
    
    print(f"Target directory: {models_dir}")
    models_dir.parent.mkdir(parents=True, exist_ok=True)
    
    if models_dir.exists():
        print("Model directory already exists. Skipping download.")
        return

    print(f"Downloading {model_name}...")
    
    # DANGEROUS: Bypass SSL verification globally for this script
    ssl._create_default_https_context = ssl._create_unverified_context
    
    try:
        # Download directly to the final location if possible or use it as cache to see if it helps
        model = SentenceTransformer(model_name, cache_folder=str(models_dir.parent))
        print("Download complete. Saving/Moving to final directory...")
        model.save(str(models_dir))
        print("Saved successfully.")
    except Exception as e:
        print(f"Error downloading model: {e}")

if __name__ == "__main__":
    download_model()
