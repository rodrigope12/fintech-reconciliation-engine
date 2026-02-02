#!/bin/bash
set -e

echo "Starting rebuild process..."

# 1. Clean previous builds
echo "Cleaning cleanup..."
rm -rf backend/build backend/dist
rm -rf dist
rm -rf frontend_src-tauri/target

# 2. Build Backend (PyInstaller)
echo "Building Backend..."
cd backend
source venv/bin/activate
pip install -r requirements.txt
pyinstaller backend.spec
deactivate
cd ..

# 3. Prepare Sidecar
echo "Preparing Sidecar..."
TARGET_ARCH="aarch64-apple-darwin"
BINARY_NAME="conciliacion-backend"
SIDECAR_DIR="frontend_src-tauri/binaries"
SIDECAR_PATH="${SIDECAR_DIR}/${BINARY_NAME}-${TARGET_ARCH}"

mkdir -p "${SIDECAR_DIR}"
cp "backend/dist/${BINARY_NAME}" "${SIDECAR_PATH}"

echo "Sidecar copied to ${SIDECAR_PATH}"

# 4. Build Frontend & Tauri App
echo "Building Tauri App..."
# Check if we should use 'npm' or 'pnpm' or 'yarn'. Package-lock.json implies npm.
npm install
npm run tauri:build

echo "Build complete!"
