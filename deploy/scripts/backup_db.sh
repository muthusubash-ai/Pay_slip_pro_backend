#!/bin/bash
# ==============================================================================
# PAYSLIP PRO - AUTOMATED POSTGRESQL DATABASE BACKUP SCRIPT
# Specifically designed for Hostinger KVM 1 Linux VPS
# ==============================================================================
# Suggested Cron Job (Runs every night at 2:00 AM):
# 0 2 * * * /var/www/backend/deploy/scripts/backup_db.sh >> /var/log/payslippro_backup.log 2>&1
# ==============================================================================

set -e

# Configurations
PROJECT_DIR="/var/www"
BACKUP_DIR="/var/backups/payslippro"
RETENTION_DAYS=7
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/payslip_backup_${TIMESTAMP}.sql.gz"

# Ensure backup directory exists with restricted permissions
mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}"

# Extract database details from backend .env if available, or fallback to standard variables
if [ -f "${PROJECT_DIR}/backend/.env" ]; then
    export $(grep -v '^#' "${PROJECT_DIR}/backend/.env" | grep -E '^DATABASE_URL=' | xargs)
fi

echo "[$(date +"%Y-%m-%d %H:%M:%S")] Starting PostgreSQL backup..."

# Perform pg_dump with gzip compression
if [ -n "${DATABASE_URL}" ]; then
    pg_dump "${DATABASE_URL}" --clean --if-exists --no-owner --no-privileges | gzip > "${BACKUP_FILE}"
else
    # Fallback default local db
    DB_NAME="${DB_NAME:-payslip_db}"
    DB_USER="${DB_USER:-payslip_user}"
    pg_dump -U "${DB_USER}" -d "${DB_NAME}" --clean --if-exists --no-owner --no-privileges | gzip > "${BACKUP_FILE}"
fi

# Check backup file size and status
BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[$(date +"%Y-%m-%d %H:%M:%S")] ✓ Backup successfully completed: ${BACKUP_FILE} (${BACKUP_SIZE})"

# Enforce Retention Policy: Remove backups older than 7 days to preserve NVMe disk space
echo "[$(date +"%Y-%m-%d %H:%M:%S")] Cleaning up backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -type f -name "payslip_backup_*.sql.gz" -mtime +${RETENTION_DAYS} -exec rm -f {} \;

echo "[$(date +"%Y-%m-%d %H:%M:%S")] ✓ Backup routine finished cleanly."
