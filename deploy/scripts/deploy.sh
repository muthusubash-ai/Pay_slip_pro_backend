#!/bin/bash
# ==============================================================================
# PAYSLIP PRO - ONE-COMMAND DEPLOYMENT & UPDATE SCRIPT
# Specifically designed for Hostinger KVM 1 Linux VPS (Ubuntu 22.04 / 24.04)
# ==============================================================================
# Run as root or with sudo:
# sudo /var/www/backend/deploy/scripts/deploy.sh
# ==============================================================================
# backend and frontend are two SEPARATE git repos (their own GitHub remotes),
# both cloned directly under /var/www - not nested inside a shared project
# folder - so each is pulled independently below.
# ==============================================================================

set -e

PROJECT_DIR="/var/www"
BACKEND_DIR="${PROJECT_DIR}/backend"
FRONTEND_DIR="${PROJECT_DIR}/frontend"

echo "===================================================================="
echo "🚀 Starting PaySlipPro Production Deployment on Hostinger KVM 1..."
echo "===================================================================="

# 1. Pull latest code in both repos
echo "[1/6] Pulling latest updates from Git..."
if [ -d "${BACKEND_DIR}/.git" ]; then
    (cd "${BACKEND_DIR}" && git pull origin main) || echo "Backend git pull skipped (working tree dirty or detached)."
else
    echo "Backend git directory not detected, proceeding with existing files..."
fi
if [ -d "${FRONTEND_DIR}/.git" ]; then
    (cd "${FRONTEND_DIR}" && git pull origin main) || echo "Frontend git pull skipped (working tree dirty or detached)."
else
    echo "Frontend git directory not detected, proceeding with existing files..."
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
mkdir -p "${BACKEND_DIR}/media" "${BACKEND_DIR}/uploads" "${BACKEND_DIR}/logs"
# Scoped to BACKEND_DIR/FRONTEND_DIR only, not PROJECT_DIR - PROJECT_DIR is now
# the shared /var/www web root, which can hold other sites (e.g. /var/www/certbot)
# that must not be touched by this script.
chown -R www-data:www-data "${BACKEND_DIR}" "${FRONTEND_DIR}"
chmod -R 755 "${BACKEND_DIR}" "${FRONTEND_DIR}"
chmod -R 775 "${BACKEND_DIR}/media" "${BACKEND_DIR}/uploads" "${BACKEND_DIR}/logs"
chmod +x "${BACKEND_DIR}/deploy/scripts/"*.sh

# 6. Restart Gunicorn & Reload Nginx
echo "[6/6] Reloading system services..."
systemctl daemon-reload
# The actual systemd unit on this server is payslip_backend.service (set up
# manually, binding gunicorn to 127.0.0.1:8000) - not payslippro.service from
# deploy/systemd/payslippro.service, which was never actually installed here.
systemctl restart payslip_backend.service
systemctl reload nginx

echo "===================================================================="
echo "✓ Deployment complete! Application is running live."
echo "Status check: sudo systemctl status payslip_backend.service"
echo "===================================================================="
