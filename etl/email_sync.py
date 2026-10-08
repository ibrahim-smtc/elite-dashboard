import os
import time
import imaplib
import email
from email.header import decode_header
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

EMAIL_USER = os.getenv('EMAIL_SYNC_USER')
EMAIL_PASS = os.getenv('EMAIL_SYNC_PASS')
IMAP_SERVER = 'imap.gmail.com'
POLL_INTERVAL_SECONDS = 60

DOWNLOAD_DIR = Path(__file__).resolve().parent.parent / 'tmp'
DOWNLOAD_DIR.mkdir(exist_ok=True)

def process_file(file_path):
    print(f"Triggering ETL for {file_path.name}")
    # FIX (2026-10-08): this call passes no --period, and load_dsr used to
    # default that to AUG2026 - so every emailed workbook replaced August,
    # whatever month it was for. load_dsr now reads the month from the
    # attachment's file name and refuses one that does not say (logged in the
    # error branch below; the email is already marked read, so resend it with
    # the month in the file name).
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

def check_for_emails():
    if not EMAIL_USER or EMAIL_USER == 'YOUR_EMAIL_ADDRESS_HERE':
        print("EMAIL_SYNC_USER is not set correctly in .env. Skipping email check.")
        return

    try:
        # Connect to IMAP server
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        # Search for unread emails
        status, messages = mail.search(None, '(UNSEEN)')
        if status != "OK":
            print("Failed to search emails.")
            return

        email_ids = messages[0].split()
        if not email_ids:
            # No new emails
            pass
        else:
            print(f"Found {len(email_ids)} total unread emails.")
            # Only process the 50 newest unread emails to prevent massive downloads
            email_ids = email_ids[-50:]
            print(f"Processing the {len(email_ids)} newest unread emails.")

        for e_id in email_ids:
            status, msg_data = mail.fetch(e_id, '(RFC822)')
            if status != "OK":
                continue

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    
                    processed_any = False
                    for part in msg.walk():
                        if part.get_content_maintype() == 'multipart':
                            continue
                        if part.get('Content-Disposition') is None:
                            continue

                        filename = part.get_filename()
                        if filename and filename.endswith('.xlsx'):
                            print(f"Found attachment: {filename}")
                            file_path = DOWNLOAD_DIR / filename
                            
                            with open(file_path, 'wb') as f:
                                f.write(part.get_payload(decode=True))

                            try:
                                success = process_file(file_path)
                            finally:
                                # PII POLICY (2026-10-08): the attachment is the
                                # raw DSR, with every customer's phone, email and
                                # address. It used to stay in tmp/ forever; it is
                                # deleted once loaded (or failed).
                                file_path.unlink(missing_ok=True)
                            if success:
                                processed_any = True

                    # If we processed an attachment, we can leave it as seen (fetch automatically marks as SEEN)
                    # If we wanted to flag it, we could do: mail.store(e_id, '+FLAGS', '\\Seen')
                    
        mail.logout()
    except Exception as e:
        print(f"Error checking emails: {e}")

if __name__ == '__main__':
    print(f"Starting Email Sync Daemon for: {EMAIL_USER}")
    print(f"Polling every {POLL_INTERVAL_SECONDS} seconds...")
    while True:
        check_for_emails()
        time.sleep(POLL_INTERVAL_SECONDS)
