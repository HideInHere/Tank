import jwt
import httpx


class OpenClawClient:
    def __init__(self, base_url: str, secret: str):
        self._base_url = base_url.rstrip('/')
        self._secret = secret
        self._client = httpx.AsyncClient(timeout=10.0)
        self._agent_id: str | None = None
        self._token: str | None = None

    def _auth_headers(self) -> dict:
        if self._token:
            return {'Authorization': f'Bearer {self._token}'}
        token = jwt.encode({'agent_id': self._agent_id or 'unknown'}, self._secret, algorithm='HS256')
        return {'Authorization': f'Bearer {token}'}

    async def register(self, agent_id: str, agent_type: str, capabilities: list[str]) -> dict:
        self._agent_id = agent_id
        token = jwt.encode({'agent_id': agent_id}, self._secret, algorithm='HS256')
        self._token = token
        resp = await self._client.post(
            f'{self._base_url}/agents/register',
            json={'agent_id': agent_id, 'type': agent_type, 'capabilities': capabilities},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def create_session(self) -> dict:
        resp = await self._client.post(
            f'{self._base_url}/sessions',
            json={},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        if 'token' in data:
            self._token = data['token']
        return data

    async def send_slash(self, session_id: str, command: str) -> dict:
        resp = await self._client.post(
            f'{self._base_url}/slash',
            json={'session_id': session_id, 'command': command},
            headers=self._auth_headers(),
        )
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._client.aclose()
