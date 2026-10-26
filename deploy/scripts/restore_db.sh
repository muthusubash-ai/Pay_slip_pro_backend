#!/bin/bash
# ==============================================================================
# PAYSLIP PRO - DATABASE RESTORE UTILITY
# Usage: ./restore_db.sh /var/backups/payslippro/payslip_backup_YYYYMMDD_HHMMSS.sql.gz
# Location: /var/www/backend/deploy/scripts/restore_db.sh
# ==============================================================================

set -e

BACKUP_FILE="$1"
PROJECT_DIR="/var/www"

if [ -z "${BACKUP_FILE}" ] || [ ! -f "${BACKUP_FILE}" ]; then
    echo "Error: Please provide a valid backup .sql.gz file."
    echo "Usage: $0 /path/to/backup.sql.gz"
    exit 1
fi

echo "===================================================================="
echo "WARNING: This will restore the database from: ${BACKUP_FILE}"
echo "Current tables will be overwritten with the backup state."
echo "===================================================================="
read -p "Are you sure you want to proceed? (yes/no): " CONFIRM
if [ "${CONFIRM}" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

if [ -f "${PROJECT_DIR}/backend/.env" ]; then
    export $(grep -v '^#' "${PROJECT_DIR}/backend/.env" | grep -E '^DATABASE_URL=' | xargs)
fi

echo "Restoring database..."
gunzip -c "${BACKUP_FILE}" | psql "${DATABASE_URL}"

echo "✓ Database successfully restored from ${BACKUP_FILE}!"
