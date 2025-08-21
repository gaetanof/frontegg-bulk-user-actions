import os
import json
import time
import re
import logging
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
from urllib.parse import urlencode
import requests
from dotenv import load_dotenv
import sys

# Cargar variables .env
load_dotenv()

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_list_from_env(env_var: str) -> List[str]:
    value = os.environ.get(env_var, "")
    return [item.strip() for item in value.split(",") if item.strip()]


# Entradas desde .env
USER_IDS_OR_EMAILS = load_list_from_env("USER_ID_ARRAY")
USER_ACTION_ENV = (
    os.environ.get("USER_ACTION", "").strip().lower()
)  # lock | delete | vacío


class Region(Enum):
    EU = "EU"
    US = "US"
    AP = "AP"  # Asia-Pacific


UUID_V4_RE = re.compile(
    r"^[0-9a-fA-F]{8}\-[0-9a-fA-F]{4}\-[1-5][0-9a-fA-F]{3}\-[89abAB][0-9a-fA-F]{3}\-[0-9a-fA-F]{12}$"
)


class UserBulkManager:
    # Gateways (para /auth/vendor/)
    API_GATEWAY = {
        Region.EU: "https://api.frontegg.com",
        Region.US: "https://api.us.frontegg.com",
        Region.AP: "https://api.ap.frontegg.com",
    }
    # Base de Identity (para /identity/resources/...)
    API_IDENTITY = {
        Region.EU: "https://api.frontegg.com/identity",
        Region.US: "https://api.us.frontegg.com/identity",
        Region.AP: "https://api.ap.frontegg.com/identity",
    }

    def __init__(self):
        self.client_id = os.environ.get("FRONTEGG_CLIENT_ID", "")
        self.api_token = os.environ.get("FRONTEGG_API_TOKEN", "")
        self.tenant_id = os.environ.get("FRONTEGG_TENANT_ID", "")
        region_str = os.environ.get("FRONTEGG_REGION", "EU").upper()
        try:
            self.region = Region(region_str)
        except ValueError:
            raise ValueError("FRONTEGG_REGION must be one of: EU, US, AP")

        # Rate limiting & retries
        self.rate_limit_delay = float(os.environ.get("RATE_LIMIT_DELAY", "0.5"))
        self.max_retries = int(os.environ.get("MAX_RETRIES", "3"))

        if not self.client_id or not self.api_token:
            raise ValueError("FRONTEGG_CLIENT_ID and FRONTEGG_API_TOKEN must be set")

        self.gateway = self.API_GATEWAY[self.region]
        self.identity_base = self.API_IDENTITY[self.region]

        self.default_headers = {
            "accept": "application/json",
            "content-type": "application/json",
        }
        self.bearer_token: Optional[str] = None

    # -------------------- HTTP core --------------------
    def _call_api_with_retry(
        self,
        method: str,
        url: str,
        payload: Optional[Dict] = None,
        headers: Optional[Dict] = None,
        retry_count: int = 0,
    ) -> Tuple[Optional[Dict], int, str]:
        if headers is None:
            headers = self.default_headers.copy()

        try:
            time.sleep(self.rate_limit_delay)

            if method == "GET":
                response = requests.get(url, headers=headers)
            elif method == "POST":
                response = requests.post(url, json=payload, headers=headers)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers)
            else:
                raise ValueError(f"Unsupported method {method}")

            # Rate limit
            if response.status_code == 429 and retry_count < self.max_retries:
                wait_time = (2**retry_count) * self.rate_limit_delay
                logger.warning(f"Rate limited. Retrying in {wait_time} sec...")
                time.sleep(wait_time)
                return self._call_api_with_retry(
                    method, url, payload, headers, retry_count + 1
                )

            # Success
            if response.status_code in (200, 201, 204):
                try:
                    return response.json(), response.status_code, response.text
                except Exception:
                    return {}, response.status_code, response.text

            # Error
            return None, response.status_code, response.text

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            if retry_count < self.max_retries:
                wait_time = (2**retry_count) * self.rate_limit_delay
                logger.info(f"Retrying in {wait_time} sec...")
                time.sleep(wait_time)
                return self._call_api_with_retry(
                    method, url, payload, headers, retry_count + 1
                )
            return None, 0, str(e)

    # -------------------- Auth --------------------
    def authenticate(self) -> str:
        logger.info("Authenticating with Frontegg...")
        url = f"{self.gateway}/auth/vendor/"
        body = {"clientId": self.client_id, "secret": self.api_token}
        resp_json, status, raw = self._call_api_with_retry(
            "POST", url, body, self.default_headers
        )
        if not resp_json or "token" not in resp_json:
            raise Exception(
                f"Failed to authenticate with Frontegg (status {status}): {raw}"
            )
        self.bearer_token = resp_json["token"]
        return self.bearer_token

    def _auth_headers(self) -> Dict[str, str]:
        if not self.bearer_token:
            self.authenticate()
        headers = {
            **self.default_headers,
            "authorization": f"Bearer {self.bearer_token}",
        }
        return headers

    # -------------------- Helpers --------------------
    @staticmethod
    def _looks_like_uuid(value: str) -> bool:
        return bool(UUID_V4_RE.match(value))

    def _resolve_user_id_by_email(self, email: str) -> Optional[str]:
        """
        GET /identity/resources/users/v1/email?email=<email>
        Devuelve userId o None si no existe.
        """
        headers = self._auth_headers()
        q = urlencode({"email": email})
        url = f"{self.identity_base}/resources/users/v1/email?{q}"
        resp_json, status, raw = self._call_api_with_retry("GET", url, headers=headers)
        if status == 200 and isinstance(resp_json, dict):
            uid = resp_json.get("id")
            if uid and self._looks_like_uuid(uid):
                return uid
        logger.error(
            f"Could not resolve user by email: {email} (status {status}) - {raw}"
        )
        return None

    def _ensure_user_id(self, identifier: str) -> Optional[str]:
        """Acepta UUID o email. Devuelve UUID o None si no se encuentra."""
        if self._looks_like_uuid(identifier):
            return identifier
        return self._resolve_user_id_by_email(identifier)

    # -------------------- Actions --------------------
    def lock_user(self, user_id: str) -> bool:
        """
        POST /identity/resources/users/v1/{userId}/lock
        """
        headers = self._auth_headers()
        url = f"{self.identity_base}/resources/users/v1/{user_id}/lock"
        resp_json, status, raw = self._call_api_with_retry("POST", url, {}, headers)
        if status in (200, 204):
            return True
        logger.error(f"API error (lock) {status}: {raw}")
        return False

    def delete_user(self, user_id: str) -> bool:
        """
        DELETE /identity/resources/users/v1/{userId}
        Si FRONTEGG_TENANT_ID está seteado, elimina al usuario de ese tenant (header frontegg-tenant-id).
        Si no, elimina globalmente.
        """
        headers = self._auth_headers()
        tenant_id = os.environ.get("FRONTEGG_TENANT_ID", "").strip()
        if tenant_id:
            headers = {**headers, "frontegg-tenant-id": tenant_id}
        url = f"{self.identity_base}/resources/users/v1/{user_id}"
        resp_json, status, raw = self._call_api_with_retry("DELETE", url, None, headers)
        if status in (200, 204):
            return True
        logger.error(f"API error (delete) {status}: {raw}")
        return False

    # -------------------- Runner --------------------
    def run(self, action: str, dry_run: bool = True) -> Dict[str, Any]:
        if not USER_IDS_OR_EMAILS:
            raise ValueError("USER_ID_ARRAY must not be empty")

        # Auth anticipada
        self._auth_headers()

        processed, failed = [], []

        for identifier in USER_IDS_OR_EMAILS:
            logger.info(
                f"{'DRY-RUN' if dry_run else 'EXECUTE'}: {action.upper()} for {identifier}"
            )

            user_id = self._ensure_user_id(identifier)
            if not user_id:
                failed.append({"identifier": identifier, "reason": "not_found"})
                continue

            if dry_run:
                processed.append(
                    {
                        "identifier": identifier,
                        "userId": user_id,
                        "action": action,
                        "status": "dry_run",
                    }
                )
                continue

            ok = False
            if action == "lock":
                ok = self.lock_user(user_id)
            elif action == "delete":
                ok = self.delete_user(user_id)
            else:
                raise ValueError("Invalid action, must be 'lock' or 'delete'")

            if ok:
                processed.append(
                    {
                        "identifier": identifier,
                        "userId": user_id,
                        "action": action,
                        "status": "success",
                    }
                )
            else:
                failed.append(
                    {
                        "identifier": identifier,
                        "userId": user_id,
                        "action": action,
                        "status": "failed",
                    }
                )

        return {
            "success": len(failed) == 0,
            "action": action,
            "dry_run": dry_run,
            "processed_count": len(processed),
            "failed_count": len(failed),
            "processed": processed,
            "failed": failed,
        }


def main():
    import argparse

    # No usamos choices para poder validar nosotros y dar un mensaje claro si falta la acción
    parser = argparse.ArgumentParser(
        description="Bulk lock or delete users in Frontegg (IDs or emails)."
    )
    parser.add_argument(
        "--action",
        help="Action to perform: lock or delete (can also be set via USER_ACTION env)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the action (default: dry-run)",
    )
    args = parser.parse_args()

    # Resolver acción: CLI tiene prioridad sobre .env
    action = (args.action or USER_ACTION_ENV).strip().lower()
    allowed = {"lock", "delete"}

    if action not in allowed:
        # Mensaje claro para el cliente
        msg = (
            "\n⚠️  Missing or invalid action.\n\n"
            "You need to tell the script what to do before running it.\n"
            "Specify an action either via CLI or .env:\n\n"
            "  • CLI:\n"
            "      python app.py --action lock\n"
            "      python app.py --action delete\n\n"
            "  • .env:\n"
            "      USER_ACTION=lock   # or delete\n\n"
            "Tip: run a dry-run first (no changes):\n"
            "      python app.py --action lock\n"
            "Then execute for real:\n"
            "      python app.py --action lock --execute\n"
        )
        print(msg)
        sys.exit(2)

    dry_run = not args.execute

    manager = UserBulkManager()
    result = manager.run(action, dry_run)

    print(json.dumps(result, indent=2))
    if dry_run:
        print(
            f"\nSUMMARY: would {action} {result['processed_count']} user(s); failed to resolve {result['failed_count']}."
        )
    else:
        print(
            f"\nSUMMARY: {action} success for {result['processed_count']} user(s); failures: {result['failed_count']}."
        )


if __name__ == "__main__":
    main()
