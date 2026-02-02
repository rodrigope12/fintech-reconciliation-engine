#!/bin/bash

# Define variables
MODEL_ID="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
BASE_URL="https://hf-mirror.com/${MODEL_ID}/resolve/main"
TARGET_DIR="backend/data/models/paraphrase-multilingual-MiniLM-L12-v2"

# Create target directory
mkdir -p "${TARGET_DIR}"
mkdir -p "${TARGET_DIR}/1_Pooling"

echo "Downloading model to ${TARGET_DIR}..."

# Function to download a file
download_file() {
    local file_path=$1
    local url="${BASE_URL}/${file_path}"
    local output="${TARGET_DIR}/${file_path}"
    
    echo "Downloading ${file_path}..."
    curl -k -L -f -o "${output}" "${url}"
    
    if [ $? -eq 0 ]; then
        echo "Successfully downloaded ${file_path}"
    else
        echo "Failed to download ${file_path}"
    fi
}

# List of files to download
download_file "config.json"
download_file "pytorch_model.bin"
download_file "tokenizer.json"
download_file "tokenizer_config.json"
download_file "special_tokens_map.json"
download_file "vocab.txt"
download_file "sentence_bert_config.json"
download_file "modules.json"
download_file "README.md"
download_file "1_Pooling/config.json"

echo "Download complete."
