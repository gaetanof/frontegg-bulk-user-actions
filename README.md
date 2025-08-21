Frontegg Bulk User Actions (Lock/Delete)

CLI script to lock (lock) or delete (delete) users in Frontegg in bulk, accepting both emails and IDs (UUIDs).
By default, the script runs in dry-run mode (no changes) unless you explicitly use --execute.

⸻

🚀 Requirements
• Python 3.9+
• Packages: requests, python-dotenv
• Frontegg Vendor credentials: FRONTEGG_CLIENT_ID and FRONTEGG_API_TOKEN

Recommended: use a virtual environment (venv) per project.

python3 -m venv venv
source venv/bin/activate
pip install requests python-dotenv

⸻

⚙️ Configuration 1. Create a .env file in the same folder as app.py.

Example .env:

# Frontegg API Configuration

FRONTEGG_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
FRONTEGG_API_TOKEN=yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy
FRONTEGG_TENANT_ID= # (optional) if set, DELETE will act only within that tenant
FRONTEGG_REGION=EU # EU | US | AP

# Rate Limiting Configuration

RATE_LIMIT_DELAY=0.5 # seconds between requests
MAX_RETRIES=3

# Bulk Action Configuration

USER_ID_ARRAY=user1@company.com,user2@company.com,3f7ac2e3-55c7-4dcb-9b9a-0f8f6f0b9d1a
USER_ACTION=lock # lock | delete (can be overridden by CLI)

Key variables
• USER_ID_ARRAY: comma-separated list of emails or user IDs (UUIDs).
• If you pass an email, the script resolves the userId via the API GET /identity/resources/users/v1/email?email=....
• If you pass a UUID, it is used directly.
• USER_ACTION: default action if not passed via CLI. Allowed values: lock or delete.
• FRONTEGG_TENANT_ID (optional):
• For DELETE: if set, the user is removed from that tenant (using header frontegg-tenant-id).
• If not set, the user is deleted globally.
• FRONTEGG_REGION: EU | US | AP.

⸻

▶️ Usage

1. Dry-run (default, no changes)

python app.py --action lock

# or using the value from .env

python app.py

2. Execute for real

python app.py --action lock --execute
python app.py --action delete --execute

If you don’t specify --action and USER_ACTION is missing/invalid, the program will show a clear error message with usage instructions and stop.

⸻

🧠 Supported Actions
• lock: blocks a user (prevents login).
• Endpoint: POST /identity/resources/users/v1/{userId}/lock
• delete: removes a user (globally or from a tenant if FRONTEGG_TENANT_ID is set).
• Endpoint: DELETE /identity/resources/users/v1/{userId}
• Optional header: frontegg-tenant-id: <FRONTEGG_TENANT_ID>
• email → userId resolution:
• Endpoint: GET /identity/resources/users/v1/email?email=<email>

Authentication is done via:
POST {gateway}/auth/vendor/
Gateways by region:
• EU: https://api.frontegg.com
• US: https://api.us.frontegg.com
• AP: https://api.ap.frontegg.com

⸻

🧪 Examples

Dry-run lock with mixed emails and IDs

python app.py --action lock

Expected summary:

SUMMARY: would lock 3 user(s); failed to resolve 0.

Execute delete for a tenant

.env:

FRONTEGG_TENANT_ID=b44c26fc-1a89-4b23-9156-e5daa779b517
USER_ID_ARRAY=user1@company.com,user2@company.com
USER_ACTION=delete

Run:

python app.py --execute

Result: those users are deleted from the tenant (not globally).

⸻

🧩 Quick Commands
• Dry-run with action from .env:

python app.py

    •	Dry-run overriding action:

python app.py --action lock

    •	Execute real changes:

python app.py --action delete --execute

    •	Activate venv:

source venv/bin/activate

⸻

🛟 Troubleshooting

1. Missing or invalid action
   • Neither --action nor a valid USER_ACTION (lock/delete) provided.
   • Solution: pass --action lock or add USER_ACTION=lock to .env.

2. Failed to authenticate with Frontegg (401)
   • Check FRONTEGG_CLIENT_ID, FRONTEGG_API_TOKEN.
   • Make sure .env is in the same folder as app.py.
   • Region must match your tenant (EU/US/AP).

3. User not found when using email
   • Verify the email exists in Frontegg and matches exactly.
   • The script uses GET /identity/resources/users/v1/email.

4. “User locked but UI doesn’t show it”
   • Confirm you’re calling the correct region.
   • Refresh UI or check for caching.

5. externally-managed-environment error on macOS/Homebrew
   • Use a venv:

python3 -m venv venv
source venv/bin/activate
pip install requests python-dotenv

⸻

📦 Dependencies

requirements.txt (optional):

requests
python-dotenv

Install:

pip install -r requirements.txt

⸻

🔒 Best Practices
• Always run in dry-run first.
• Test with a small set of users before running in production.
• Use FRONTEGG_TENANT_ID for scoped deletes, to avoid global deletions by mistake.
• Back up/export data before mass deletions.

⸻

❓ FAQ

Can I mix emails and IDs?
Yes. The script auto-detects UUIDs, otherwise resolves by email.

Which region should I use?
Set FRONTEGG_REGION (EU | US | AP) to match your tenant.

Can I delete only from a tenant without global removal?
Yes: set FRONTEGG_TENANT_ID. The script will send the header and remove the user only from that tenant.

What does dry-run do?
It resolves IDs, validates the API calls, and prints what would happen without making changes.
