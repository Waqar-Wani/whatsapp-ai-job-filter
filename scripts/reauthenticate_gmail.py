#!/usr/bin/env python3
"""Re-authenticate with Gmail API and refresh token."""

import sys
import os
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

def main():
    load_dotenv(PROJECT_ROOT / ".env")
    
    client_secret_file = os.getenv("GMAIL_OAUTH_CLIENT_SECRET_FILE")
    token_file = os.getenv("GMAIL_TOKEN_FILE")
    
    if not client_secret_file or not Path(client_secret_file).exists():
        print(f"❌ Client secret file not found: {client_secret_file}")
        return 1
    
    print(f"Re-authenticating Gmail API...")
    print(f"Client Secret: {client_secret_file}")
    print(f"Token File: {token_file}")
    print()
    
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        
        GMAIL_SEND_SCOPE = ["https://www.googleapis.com/auth/gmail.send"]
        
        # Delete old token to force re-authentication
        token_path = Path(token_file)
        if token_path.exists():
            token_path.unlink()
            print(f"Deleted expired token: {token_path}")
        
        # Launch OAuth flow
        print("\nLaunching Gmail OAuth consent flow...")
        print("A browser window will open. Please sign in and grant access.")
        print()
        
        flow = InstalledAppFlow.from_client_secrets_file(
            str(client_secret_file), 
            GMAIL_SEND_SCOPE
        )
        creds = flow.run_local_server(port=0)
        
        # Save the new token
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        
        print(f"✅ Gmail API re-authenticated successfully!")
        print(f"Token saved to: {token_path}")
        print("\nYou can now send emails. Run: python scripts/test_gmail_send.py")
        return 0
        
    except Exception as exc:
        print(f"❌ Re-authentication failed: {exc}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
