#!/bin/bash
# Metriplex deploy — pulls latest from GitHub to VPS
VPS="root@157.180.113.24"
echo "Deploying to VPS..."
ssh $VPS "cd /var/www/metriplexmpx.xyz && git pull origin main 2>/dev/null || echo 'no git, copying manually'"
echo "Done — https://metriplexmpx.xyz"
