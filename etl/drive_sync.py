import os
import json
import time
import io
import subprocess
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Configuration
SERVICE_ACCOUNT_FILE = 'nodal-operand-434003-p2-3769c8bfc8a7.json'
FOLDER_ID = '1SiOAdoLzju9thY_JEVZO1_rgzDB72K6W'
STATE_FILE = Path(__file__).resolve().parent.parent / 'drive_sync_state.json'
DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / 'tmp'
SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
POLL_INTERVAL_SECONDS = 60

def load_state():
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def authenticate():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

def download_file(service, file_id, file_name):
    DOWNLOAD_DIR.mkdir(exist_ok=True)
    file_path = DOWNLOAD_DIR / file_name
    
    request = service.files().get_media(fileId=file_id)
    with io.FileIO(file_path, 'wb') as fh:
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            print(f"Downloading {file_name} ... {int(status.progress() * 100)}%")
            
    return file_path

def process_file(file_path):
    print(f"Triggering ETL for {file_path.name}")
    # FIX (2026-10-08): this call passes no --period, and load_dsr used to
    # default that to AUG2026 - so every workbook dropped in the Drive folder
    # replaced August, whatever month it was for. load_dsr now reads the month
    # from the file name ("DSR September 2026.xlsx" -> SEP2026) and refuses a
    # name that does not say, which lands in the error branch below and is
    # retried on the next poll until the file is renamed.
    # Run the ETL load_dsr module as a subprocess so it stays isolated and correctly loads dotenv
    result = subprocess.run([
        "python", "-u", "-m", "etl.load_dsr", 
        "--file", str(file_path)
    ], capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"Successfully processed {file_path.name}")
        print(result.stdout)
        return True
    else:
        print(f"Error processing {file_path.name}:")
        print(result.stderr)
        return False

def check_for_updates():
    try:
        service = authenticate()
        state = load_state()
        
        # Query for excel files in the folder
        query = f"'{FOLDER_ID}' in parents and mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' and trashed=false"
        results = service.files().list(
            q=query,
            fields="files(id, name, modifiedTime)",
            pageSize=10
        ).execute()
        
        items = results.get('files', [])
        
        if not items:
            return
            
        for item in items:
            file_id = item['id']
            modified_time = item['modifiedTime']
            file_name = item['name']
            
            # Check if this file is new or modified
            if file_id not in state or state[file_id] != modified_time:
                print(f"New or modified file detected: {file_name} ({modified_time})")
                file_path = None
                try:
                    file_path = download_file(service, file_id, file_name)
                    success = process_file(file_path)

                    if success:
                        state[file_id] = modified_time
                        save_state(state)

                except Exception as e:
                    print(f"Failed to process {file_name}: {e}")
                finally:
                    # PII POLICY (2026-10-08): the downloaded workbook is the
                    # raw DSR - every customer's phone, email and address,
                    # unredacted. It used to be left in tmp/ forever. It is
                    # deleted once loaded (or failed); the next poll downloads
                    # it again if it needs retrying.
                    if file_path is not None:
                        Path(file_path).unlink(missing_ok=True)
                    
    except Exception as e:
        print(f"Error checking Google Drive: {e}")

if __name__ == '__main__':
    print(f"Starting Google Drive Sync Daemon for Folder ID: {FOLDER_ID}")
    print(f"Polling every {POLL_INTERVAL_SECONDS} seconds...")
    while True:
        check_for_updates()
        time.sleep(POLL_INTERVAL_SECONDS)
