"""Cliente HTTP assíncrono da API v2 do ClickUp, **somente leitura**.

Regras (ver `ARCHITECTURE.md` › "Integração com o ClickUp"):

- Só existem métodos GET. Não há nenhuma função de escrita, e não deve haver.
- O esquema de autenticação é um parâmetro. O token pessoal do bot vai sem
  prefixo (`Authorization: pk_...`); o `Bearer` fica pronto para o token OAuth
  da Fase 2.
- Uma instância por token (o rate limit do ClickUp é por token), com limite
  preventivo próprio, ajustado pelos headers `X-RateLimit-*` quando vierem.
- Retries com backoff exponencial e jitter, até 5 tentativas: 429 espera até o
  `X-RateLimit-Reset`; 5xx, timeout e erro de rede usam backoff; 401, 403 e 404
  não têm retry.
- O token nunca aparece em logs, `repr` ou mensagens de erro.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import random
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Generator, Sequence
from typing import TYPE_CHECKING, Any, Self

import httpx
from pydantic import SecretStr

from scarlet_scribe.connectors.clickup.schemas import (
    ClickUpFolder,
    ClickUpFoldersResponse,
    ClickUpList,
    ClickUpListsResponse,
    ClickUpSpace,
    ClickUpSpacesResponse,
    ClickUpTask,
    ClickUpTasksPage,
    ClickUpTeam,
    ClickUpTeamsResponse,
    ClickUpUser,
    ClickUpUserResponse,
)

if TYPE_CHECKING:
    from scarlet_scribe.config import Settings

logger = logging.getLogger(__name__)

BASE_URL = "https://api.clickup.com/api/v2"
TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 1.0
DEFAULT_RATE_LIMIT_PER_MINUTE = 100
TASKS_PAGE_SIZE = 100

_RATE_WINDOW_SECONDS = 60.0
# `X-RateLimit-Reset` acima disto é tratado como milissegundos.
_RESET_MS_THRESHOLD = 10**12
# Teto de espera por um `X-RateLimit-Reset` (a janela do ClickUp é de 1 minuto).
_MAX_RESET_WAIT_SECONDS = 90.0

type Params = list[tuple[str, str]]
type Sleep = Callable[[float], Awaitable[None]]


# --- Erros -----------------------------------------------------------------


class ClickUpError(Exception):
    """Erro base do conector do ClickUp. A mensagem nunca contém o token."""


class ClickUpConfigError(ClickUpError):
    """Configuração ausente ou inválida (por exemplo, sem `CLICKUP_API_TOKEN`)."""


class ClickUpAuthError(ClickUpError):
    """HTTP 401: token inválido ou revogado. Sem retry."""


class ClickUpHTTPError(ClickUpError):
    """Resposta HTTP de erro sem retry (ou com as tentativas esgotadas)."""

    def __init__(self, message: str, *, status_code: int | None, path: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.path = path


class ClickUpResourceError(ClickUpHTTPError):
    """403 ou 404 num recurso específico. O chamador decide (o sync registra e segue)."""


class ClickUpForbiddenError(ClickUpResourceError):
    """HTTP 403."""


class ClickUpNotFoundError(ClickUpResourceError):
    """HTTP 404."""


class ClickUpRateLimitError(ClickUpHTTPError):
    """HTTP 429 persistente depois de todas as tentativas."""


class ClickUpUnavailableError(ClickUpHTTPError):
    """5xx, timeout ou erro de rede persistente depois de todas as tentativas."""


# --- Autenticação ----------------------------------------------------------


class AuthScheme(enum.StrEnum):
    """Como o token vai no header `Authorization`."""

    # Token pessoal (`pk_...`) do bot: vai sem prefixo.
    PERSONAL_TOKEN = "personal_token"
    # (Fase 2) Token OAuth de uma pessoa: vai com `Bearer `.
    BEARER = "bearer"


class _TokenAuth(httpx.Auth):
    """Injeta o `Authorization` em cada requisição sem expor o token em `repr`."""

    def __init__(self, token: SecretStr, scheme: AuthScheme) -> None:
        self._token = token
        self._scheme = scheme

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        secret = self._token.get_secret_value()
        if self._scheme is AuthScheme.BEARER:
            request.headers["Authorization"] = f"Bearer {secret}"
        else:
            request.headers["Authorization"] = secret
        yield request

    def __repr__(self) -> str:
        return f"<_TokenAuth scheme={self._scheme.value}>"


# --- Rate limit preventivo -------------------------------------------------


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(float(value.strip()))
    except ValueError:
        return None


def _seconds_until_reset(headers: httpx.Headers) -> float | None:
    """Segundos até o `X-RateLimit-Reset` (Unix; acima de 10¹² é ms). None se ausente."""
    reset = _int_header(headers, "X-RateLimit-Reset")
    if reset is None:
        return None
    reset_seconds = reset / 1000 if reset > _RESET_MS_THRESHOLD else float(reset)
    wait = reset_seconds - time.time()
    return min(max(wait, 0.0), _MAX_RESET_WAIT_SECONDS)


class _RateLimiter:
    """Janela deslizante de 60 s por instância (portanto por token).

    O limite efetivo é o menor entre o configurado e o `X-RateLimit-Limit`
    informado pelo ClickUp. Se a API disser que não resta nenhuma requisição
    (`X-RateLimit-Remaining: 0`), novas requisições esperam até o `Reset`.
    """

    def __init__(self, per_minute: int, sleep: Sleep) -> None:
        if per_minute < 1:
            raise ClickUpConfigError("CLICKUP_RATE_LIMIT_PER_MINUTE deve ser pelo menos 1")
        self._configured = per_minute
        self.limit = per_minute
        self._sleep = sleep
        self._sent: deque[float] = deque()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                if self._blocked_until > now:
                    await self._sleep(self._blocked_until - now)
                    continue
                while self._sent and now - self._sent[0] >= _RATE_WINDOW_SECONDS:
                    self._sent.popleft()
                if len(self._sent) < self.limit:
                    self._sent.append(now)
                    return
                await self._sleep(self._sent[0] + _RATE_WINDOW_SECONDS - now)

    def block_for(self, seconds: float) -> None:
        self._blocked_until = max(self._blocked_until, time.monotonic() + seconds)

    def observe(self, headers: httpx.Headers) -> None:
        server_limit = _int_header(headers, "X-RateLimit-Limit")
        if server_limit is not None and server_limit > 0:
            self.limit = min(self._configured, server_limit)
        remaining = _int_header(headers, "X-RateLimit-Remaining")
        if remaining is not None and remaining <= 0:
            wait = _seconds_until_reset(headers)
            if wait is not None:
                self.block_for(wait)


# --- Cliente ---------------------------------------------------------------


def _bool(value: bool) -> str:
    return "true" if value else "false"


class ClickUpClient:
    """Cliente somente leitura da API v2 do ClickUp.

    Uma instância por token e por execução de sync:

        async with ClickUpClient(token, rate_limit_per_minute=100) as client:
            teams = await client.get_teams()
    """

    def __init__(
        self,
        token: str | SecretStr,
        *,
        auth_scheme: AuthScheme = AuthScheme.PERSONAL_TOKEN,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        max_attempts: int = MAX_ATTEMPTS,
        backoff_base_seconds: float = BACKOFF_BASE_SECONDS,
        base_url: str = BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        secret = token if isinstance(token, SecretStr) else SecretStr(token)
        if not secret.get_secret_value().strip():
            raise ClickUpConfigError("token do ClickUp vazio")
        self._auth_scheme = auth_scheme
        self._max_attempts = max(1, max_attempts)
        self._backoff_base = backoff_base_seconds
        self._sleep = sleep
        self._limiter = _RateLimiter(rate_limit_per_minute, sleep)
        self._http = httpx.AsyncClient(
            base_url=base_url,
            auth=_TokenAuth(secret, auth_scheme),
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            headers={"Accept": "application/json"},
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> Self:
        """Cliente do bot (token pessoal), com o limite de `CLICKUP_RATE_LIMIT_PER_MINUTE`."""
        if settings.clickup_api_token is None:
            raise ClickUpConfigError("CLICKUP_API_TOKEN não está definido")
        kwargs.setdefault("rate_limit_per_minute", settings.clickup_rate_limit_per_minute)
        return cls(settings.clickup_api_token, auth_scheme=AuthScheme.PERSONAL_TOKEN, **kwargs)

    def __repr__(self) -> str:
        return (
            f"ClickUpClient(auth_scheme={self._auth_scheme.value!r}, "
            f"rate_limit_per_minute={self._limiter.limit})"
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- Endpoints de leitura (Fase 1) -------------------------------------

    async def get_user(self) -> ClickUpUser:
        """`GET /v2/user`: o dono do token. Serve para validar o token no início do sync."""
        data = await self._get("/user")
        return ClickUpUserResponse.model_validate(data).user

    async def get_teams(self) -> list[ClickUpTeam]:
        """`GET /v2/team`: workspaces visíveis ao token, com `members[].user`."""
        data = await self._get("/team")
        return ClickUpTeamsResponse.model_validate(data).teams

    async def get_spaces(self, team_id: str, *, archived: bool = False) -> list[ClickUpSpace]:
        """`GET /v2/team/{team_id}/space`."""
        data = await self._get(f"/team/{team_id}/space", [("archived", _bool(archived))])
        return ClickUpSpacesResponse.model_validate(data).spaces

    async def get_folders(self, space_id: str, *, archived: bool = False) -> list[ClickUpFolder]:
        """`GET /v2/space/{space_id}/folder`. Subfolders vêm na mesma lista, com `parent_folder`."""
        data = await self._get(f"/space/{space_id}/folder", [("archived", _bool(archived))])
        return ClickUpFoldersResponse.model_validate(data).folders

    async def get_folder_lists(self, folder_id: str, *, archived: bool = False) -> list[ClickUpList]:
        """`GET /v2/folder/{folder_id}/list`: lists de um folder."""
        data = await self._get(f"/folder/{folder_id}/list", [("archived", _bool(archived))])
        return ClickUpListsResponse.model_validate(data).lists

    async def get_folderless_lists(self, space_id: str, *, archived: bool = False) -> list[ClickUpList]:
        """`GET /v2/space/{space_id}/list`: lists fora de folders."""
        data = await self._get(f"/space/{space_id}/list", [("archived", _bool(archived))])
        return ClickUpListsResponse.model_validate(data).lists

    async def iter_task_pages(
        self,
        team_id: str,
        *,
        date_updated_gt: int | None = None,
        space_ids: Sequence[str] | None = None,
    ) -> AsyncIterator[list[ClickUpTask]]:
        """`GET /v2/team/{team_id}/task`, página a página (100 tarefas, `page` a partir de 0).

        Envia `subtasks=true&include_closed=true`. A resposta não tem `last_page`:
        a paginação para na primeira página com menos de 100 tarefas.

        `date_updated_gt` é um Unix em ms (sync incremental). `space_ids` vira
        `space_ids[]` repetido.
        """
        base: Params = [("subtasks", "true"), ("include_closed", "true")]
        if date_updated_gt is not None:
            base.append(("date_updated_gt", str(date_updated_gt)))
        for space_id in space_ids or ():
            base.append(("space_ids[]", str(space_id)))

        page = 0
        while True:
            data = await self._get(f"/team/{team_id}/task", [*base, ("page", str(page))])
            tasks = ClickUpTasksPage.model_validate(data).tasks
            if tasks:
                yield tasks
            if len(tasks) < TASKS_PAGE_SIZE:
                return
            page += 1

    # --- Núcleo: GET com rate limit e retries ------------------------------

    def _backoff(self, attempt: int) -> float:
        delay = self._backoff_base * (2 ** (attempt - 1))
        return delay + random.uniform(0, delay / 4)

    def _unauthorized_message(self) -> str:
        if self._auth_scheme is AuthScheme.PERSONAL_TOKEN:
            return "token do bot inválido ou revogado"
        return "token OAuth inválido ou revogado"

    async def _get(self, path: str, params: Params | None = None) -> Any:
        """Faz um GET relativo a `/api/v2`. Único ponto de acesso à rede do cliente."""
        for attempt in range(1, self._max_attempts + 1):
            last_attempt = attempt == self._max_attempts
            await self._limiter.acquire()
            try:
                response = await self._http.get(path, params=params)
            except httpx.TimeoutException as exc:
                if last_attempt:
                    raise ClickUpUnavailableError(
                        f"GET {path}: timeout após {self._max_attempts} tentativas",
                        status_code=None,
                        path=path,
                    ) from None
                reason = f"timeout ({type(exc).__name__})"
            except httpx.TransportError as exc:
                if last_attempt:
                    raise ClickUpUnavailableError(
                        f"GET {path}: erro de rede após {self._max_attempts} tentativas "
                        f"({type(exc).__name__})",
                        status_code=None,
                        path=path,
                    ) from None
                reason = f"erro de rede ({type(exc).__name__})"
            else:
                self._limiter.observe(response.headers)
                status = response.status_code

                if status < 300:
                    try:
                        return response.json()
                    except ValueError:
                        raise ClickUpHTTPError(
                            f"GET {path}: resposta {status} sem JSON válido",
                            status_code=status,
                            path=path,
                        ) from None

                if status == 401:
                    raise ClickUpAuthError(self._unauthorized_message())
                if status == 403:
                    raise ClickUpForbiddenError(
                        f"GET {path}: 403 sem permissão{_error_detail(response)}",
                        status_code=status,
                        path=path,
                    )
                if status == 404:
                    raise ClickUpNotFoundError(
                        f"GET {path}: 404 não encontrado{_error_detail(response)}",
                        status_code=status,
                        path=path,
                    )

                if status == 429:
                    if last_attempt:
                        raise ClickUpRateLimitError(
                            f"GET {path}: 429 após {self._max_attempts} tentativas",
                            status_code=status,
                            path=path,
                        )
                    wait = _seconds_until_reset(response.headers)
                    if wait is None:
                        wait = self._backoff(attempt)
                    else:
                        wait += random.uniform(0, 0.5)
                    # A espera fica no limitador: vale também para outras chamadas
                    # concorrentes com o mesmo token.
                    self._limiter.block_for(wait)
                    logger.warning(
                        "ClickUp GET %s: 429; nova tentativa %d/%d em %.1fs",
                        path, attempt + 1, self._max_attempts, wait,
                    )
                    continue

                if status >= 500:
                    if last_attempt:
                        raise ClickUpUnavailableError(
                            f"GET {path}: {status} após {self._max_attempts} tentativas",
                            status_code=status,
                            path=path,
                        )
                    reason = f"HTTP {status}"
                else:
                    raise ClickUpHTTPError(
                        f"GET {path}: HTTP {status}{_error_detail(response)}",
                        status_code=status,
                        path=path,
                    )

            wait = self._backoff(attempt)
            logger.warning(
                "ClickUp GET %s: %s; nova tentativa %d/%d em %.1fs",
                path, reason, attempt + 1, self._max_attempts, wait,
            )
            await self._sleep(wait)

        raise AssertionError("inalcançável")  # pragma: no cover


def _error_detail(response: httpx.Response) -> str:
    """Código de erro do ClickUp (`ECODE`) e a mensagem, se o corpo for o JSON padrão."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    err = str(body.get("err", ""))[:200]
    ecode = body.get("ECODE")
    parts = [p for p in (err, f"ECODE={ecode}" if ecode else "") if p]
    return f" ({'; '.join(parts)})" if parts else ""
