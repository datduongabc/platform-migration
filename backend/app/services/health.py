from typing import Any, Dict

import httpx


async def probe_key(config_key: str, plaintext: str) -> Dict[str, Any]:
    """
    Sends a cheap live API request to test if the API key is active.
    Returns: {"status": "healthy" | "unhealthy" | "unknown", "detail": str}
    """
    timeout = 10.0
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if config_key == "gemini_api_key":
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={plaintext}"
                res = await client.get(url)
            elif config_key == "speechmatics_api_key":
                url = "https://asr.api.speechmatics.com/v2/jobs?limit=1"
                res = await client.get(
                    url, headers={"Authorization": f"Bearer {plaintext}"}
                )
            else:
                return {
                    "status": "unknown",
                    "detail": "No probe configured for this config_key",
                }

            # Classify result based on status code
            if 200 <= res.status_code < 300:
                return {"status": "healthy", "detail": f"OK ({res.status_code})"}
            elif res.status_code == 429:
                return {
                    "status": "healthy",
                    "detail": "Rate-limited (429) - key is valid",
                }
            elif res.status_code == 401:
                return {
                    "status": "unhealthy",
                    "detail": "Rejected: invalid or revoked key (401)",
                }
            elif res.status_code == 403:
                return {
                    "status": "unhealthy",
                    "detail": "Rejected: key lacks permission (403)",
                }
            elif res.status_code >= 500:
                return {
                    "status": "unknown",
                    "detail": f"Provider error ({res.status_code}) - inconclusive",
                }
            else:
                return {
                    "status": "unknown",
                    "detail": f"Unexpected response ({res.status_code}) - inconclusive",
                }

        except httpx.HTTPError as e:
            return {
                "status": "unknown",
                "detail": f"Network error - inconclusive: {str(e)[:120]}",
            }
        except Exception as e:
            return {"status": "unknown", "detail": f"Error: {str(e)[:120]}"}
