from google.oauth2 import service_account
from googleapiclient.discovery import build

KEY = r"C:\Users\Praneet\Downloads\elite-motors-508904-acf18641074f.json"

creds = service_account.Credentials.from_service_account_file(
    KEY,
    scopes=["https://www.googleapis.com/auth/drive.readonly"],
)
drive = build("drive", "v3", credentials=creds)

res = drive.files().list(
    q="mimeType='application/vnd.google-apps.folder' and trashed=false",
    fields="files(id,name)",
    includeItemsFromAllDrives=True,
    supportsAllDrives=True,
).execute()

folders = res.get("files", [])
print(f"{len(folders)} folder(s) visible:")
for f in folders:
    print(" -", f["name"], f["id"])