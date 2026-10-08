"""Start the DSR dashboard: python run.py"""
import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    # 127.0.0.1 accepts connections from this machine only, which is why a
    # cloud agent (Perfox) cannot reach the API however the URL is written.
    # Set HOST=0.0.0.0 to listen on every interface so a tunnel or the LAN can
    # reach it. Left as loopback by default: opening a port is a decision, not
    # something a dev server should do on its own.
    host = os.environ.get("HOST", "127.0.0.1")
    # Likewise reload: handy locally, and the reason a code change used to need
    # a manual restart before it took effect.
    reload = os.environ.get("RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)

