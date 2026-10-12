#!/bin/sh
set -eu
timestamp=$(date +%Y%m%d-%H%M%S)
pg_dump -h db -U vorrat -d vorrat | gzip > "/backups/vorrat-${timestamp}.sql.gz"
find /backups -name 'vorrat-*.sql.gz' -type f -mtime +14 -delete
