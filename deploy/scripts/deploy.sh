#!/bin/bash
# ==============================================================================
# PAYSLIP PRO - ONE-COMMAND DEPLOYMENT & UPDATE SCRIPT
# Specifically designed for Hostinger KVM 1 Linux VPS (Ubuntu 22.04 / 24.04)
# ==============================================================================
# Run as root or with sudo:
# sudo /var/www/payslippro/deploy/scripts/deploy.sh
# ==============================================================================

set -e

PROJECT_DIR="/var/www/payslippro"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"

echo "===================================================================="
echo "🚀 Starting PaySlipPro Production Deployment on Hostinger KVM 1..."
echo "===================================================================="

cd "${PROJECT_DIR}"

# 1. Pull latest code if git repo
if [ -d ".git" ]; then
    echo "[1/6] Pulling latest updates from Git..."
    git pull origin main || echo "Git pull skipped (working tree dirty or detached)."
else
    echo "[1/6] Git directory not detected, proceeding with existing files..."
fi

# 2. Setup Python Virtual Environment and Backend Dependencies
echo "[2/6] Installing system build dependencies for dlib/face_recognition..."
# face_recognition requires compiling dlib from source on most Linux hosts since
# there is no universal prebuilt wheel - without cmake/a C++ compiler this pip
# install silently fails (or crashes mid-build on low-RAM VPS boxes) and every
# face-related endpoint then 503s for every employee at runtime. Modern dlib
# (19.19+) builds its own bindings via CMake + pybind11 and does not need Boost.
if [ "$(swapon --show | wc -l)" -eq 0 ]; then
    echo "WARNING: No swap detected. Compiling dlib from source is memory-heavy and" \
         "can be OOM-killed on a 1 vCPU/4GB VPS without swap (see DEPLOYMENT_HOSTINGER_KVM1.md Phase 1.2)."
fi
apt-get update -y
apt-get install -y --no-install-recommends cmake build-essential python3-dev

echo "[2/6] Updating Python backend dependencies..."
cd "${BACKEND_DIR}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -c "import face_recognition" || { echo "FATAL: face_recognition/dlib failed to import after install. Face auth and attendance punch-in will not work."; exit 1; }

# 3. Run Database Migrations & Collect Static Files
echo "[3/6] Running Django database migrations and collecting static files..."
python manage.py migrate --noinput
python manage.py collectstatic --noinput

# 4. Build React 19 Frontend
echo "[4/6] Building frontend Vite production assets..."
cd "${FRONTEND_DIR}"
if [ -f "package-lock.json" ]; then
    npm ci
else
    npm install
fi
npm run build

# 5. Fix File Permissions for Nginx & Gunicorn
echo "[5/6] Ensuring correct Linux file permissions..."
cd "${PROJECT_DIR}"
mkdir -p "${BACKEND_DIR}/media" "${BACKEND_DIR}/uploads" "${BACKEND_DIR}/logs"
chown -R www-data:www-data "${PROJECT_DIR}"
chmod -R 755 "${PROJECT_DIR}"
chmod -R 775 "${BACKEND_DIR}/media" "${BACKEND_DIR}/uploads" "${BACKEND_DIR}/logs"

# 6. Restart Gunicorn & Reload Nginx
echo "[6/6] Reloading system services..."
systemctl daemon-reload
systemctl restart payslippro.service
systemctl reload nginx

echo "===================================================================="
echo "✓ Deployment complete! Application is running live."
echo "Status check: sudo systemctl status payslippro.service"
echo "===================================================================="
