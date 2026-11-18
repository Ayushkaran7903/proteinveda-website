"""Create a backup zip (database + uploaded images) in the backups/ folder. Schedule daily with cron:
   0 2 * * *  cd /path/to/proteinveda && /path/to/python backup.py"""
import app
print("Backup saved:", app.save_server_backup())
