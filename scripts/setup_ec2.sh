#!/bin/bash
# Run this once on the EC2 instance to set up the daily cron job

REPO_DIR="/home/ubuntu/27185-nba-analytics-ml-ai-assistant"

(crontab -l 2>/dev/null; echo "0 6 * * * cd $REPO_DIR && source venv/bin/activate && python -m etl.pipeline >> $REPO_DIR/cron.log 2>&1") | crontab -

echo "Cron job set up. Pipeline runs daily at 6:00 AM UTC."
echo "Logs: $REPO_DIR/cron.log"
