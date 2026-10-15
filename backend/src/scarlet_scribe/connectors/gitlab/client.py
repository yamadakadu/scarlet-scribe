"""Cliente HTTP assíncrono da API v4 do GitLab, **somente leitura**.

Regras (ver `ARCHITECTURE.md` › "Fase M: multi-integração" › "GitLab"):

- Só existem métodos GET. Não há nenhuma função de escrita, e não deve haver.
- Autenticação: token do bot (escopo `read_api`) no header `PRIVATE-TOKEN`.
- Base `{GITLAB_URL}/api/v4`. O código não distingue gitlab.com de self-hosted;
  `GITLAB_CA_BUNDLE` (opcional) serve a certificados internos.
- Paginação por offset (`per_page=100`), seguindo `X-Next-Page` (vazio na última
  página) ou o `Link rel="next"`. Nunca usa `X-Total`, que pode não vir.
- Rate limit preventivo (`GITLAB_RATE_LIMIT_PER_MINUTE`), ajustado só para baixo
  por `RateLimit-Limit`. Com `RateLimit-Remaining: 0`, espera até o
  `RateLimit-Reset`, que é um **epoch absoluto em segundos**.
- Retries com backoff exponencial e jitter, até 5 tentativas: 429 espera o
  `Retry-After` (ou o `RateLimit-Reset`); 5xx, timeout e erro de rede usam
  backoff; 401, 403 e 404 não têm retry.
- O token nunca aparece em logs, `repr` ou mensagens de erro.
- Nenhuma exceção do httpx nem `pydantic.ValidationError` sai do cliente.
  Nas listagens, a validação é feita item a item: um item inválido é separado
  em `GitLabPage.invalid` (id e motivo, sem conteúdo) e não derruba a página.
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import random
import re
import ssl
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Generator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple, Self
from urllib.parse import parse_qs, quote, urlparse

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from scarlet_scribe.connectors.base import (
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorError,
)
from scarlet_scribe.connectors.gitlab.mapper import format_instant
from scarlet_scribe.connectors.gitlab.schemas import (
    GitLabCommit,
    GitLabMergeRequest,
    GitLabModel,
    GitLabProject,
)

if TYPE_CHECKING:
    from scarlet_scribe.config import Settings

logger = logging.getLogger(__name__)

API_PATH = "/api/v4"
TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 1.0
DEFAULT_RATE_LIMIT_PER_MINUTE = 600
PAGE_SIZE = 100
# Teto de páginas por listagem (1000 páginas = 100 mil itens). Protege contra uma
# API que ignore `page` e devolva sempre páginas cheias.
MAX_PAGES = 1000

_RATE_WINDOW_SECONDS = 60.0
# Teto de espera por um `Retry-After` ou `RateLimit-Reset` (a janela do GitLab é de 1 minuto).
_MAX_RESET_WAIT_SECONDS = 120.0

# Erros do httpx que valem retry com backoff. `ProxyError` entra porque um proxy
# indisponível se comporta como um 5xx. Os demais `httpx.RequestError` não têm retry.
_TRANSIENT_NETWORK_ERRORS = (httpx.NetworkError, httpx.RemoteProtocolError, httpx.ProxyError)

type Params = list[tuple[str, str]]
type Sleep = Callable[[float], Awaitable[None]]


# --- Erros -----------------------------------------------------------------


class GitLabError(ConnectorError):
    """Erro base do conector do GitLab. A mensagem nunca contém o token."""


class GitLabConfigError(GitLabError, ConnectorConfigError):
    """Configuração ausente ou inválida (URL, token, bundle de CA)."""


class GitLabAuthError(GitLabError, ConnectorAuthError):
    """HTTP 401: token inválido, expirado ou revogado. Sem retry."""


class GitLabHTTPError(GitLabError):
    """Resposta HTTP de erro sem retry (ou com as tentativas esgotadas)."""

    def __init__(self, message: str, *, status_code: int | None, path: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.path = path


class GitLabResourceError(GitLabHTTPError):
    """403 ou 404 num recurso específico. O chamador decide (o sync registra e segue)."""


class GitLabForbiddenError(GitLabResourceError):
    """HTTP 403."""


class GitLabNotFoundError(GitLabResourceError):
    """HTTP 404."""


class GitLabRateLimitError(GitLabHTTPError):
    """HTTP 429 persistente depois de todas as tentativas."""


class GitLabUnavailableError(GitLabHTTPError):
    """5xx, timeout ou erro de rede persistente depois de todas as tentativas."""


class GitLabPaginationError(GitLabError):
    """A paginação não terminou: página repetida ou teto de páginas atingido."""


class GitLabResponseError(GitLabError):
    """Resposta 2xx fora do formato esperado. A mensagem traz só campos e tipos de erro."""

    def __init__(self, message: str, *, path: str) -> None:
        super().__init__(message)
        self.path = path


# --- Resultado de uma página --------------------------------------------------


@dataclass(frozen=True)
class InvalidItem:
    """Item que não passou na validação do schema: só o id e o motivo, sem conteúdo."""

    item_id: str | None
    reason: str


@dataclass(frozen=True)
class GitLabPage[M: GitLabModel]:
    """Uma página de uma listagem, já validada item a item."""

    page: int
    items: list[M]
    invalid: list[InvalidItem]
    # Quantos itens vieram na resposta (válidos + inválidos).
    size: int


def validation_reason(exc: ValidationError, *, limit: int = 5) -> str:
    """Motivo de uma `ValidationError` só com o campo e o tipo do erro.

    Não usa a mensagem do Pydantic, que pode repetir o valor recebido.
    """
    parts = []
    for error in exc.errors(include_url=False, include_input=False, include_context=False)[:limit]:
        loc = ".".join(str(part) for part in error.get("loc", ())) or "(raiz)"
        parts.append(f"{loc}: {error.get('type', 'invalid')}")
    extra = exc.error_count() - limit
    if extra > 0:
        parts.append(f"+{extra} erro(s)")
    return "; ".join(parts)


def _parse[M: BaseModel](model: type[M], data: Any, path: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise GitLabResponseError(
            f"GET {path}: resposta fora do formato esperado ({validation_reason(exc)})",
            path=path,
        ) from None


def _raw_item_id(item: Any) -> str | None:
    """`id` de um item bruto (número ou sha), só para identificar descartados."""
    if isinstance(item, dict):
        value = item.get("id")
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            text = str(value).strip()
            return text[:64] or None
    return None


def quote_id(value: str | int) -> str:
    """Id ou caminho de grupo/projeto para uso numa URL (`ns/proj` vira `ns%2Fproj`)."""
    return quote(str(value), safe="")


# --- Autenticação ----------------------------------------------------------


class _TokenAuth(httpx.Auth):
    """Injeta o `PRIVATE-TOKEN` em cada requisição sem expor o token em `repr`."""

    def __init__(self, token: SecretStr) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["PRIVATE-TOKEN"] = self._token.get_secret_value()
        yield request

    def __repr__(self) -> str:
        return "<_TokenAuth PRIVATE-TOKEN>"


def _ssl_context(ca_bundle: str | None) -> ssl.SSLContext | bool:
    """Contexto TLS com o bundle de CA próprio; `True` (padrão do httpx) quando vazio."""
    if not ca_bundle or not ca_bundle.strip():
        return True
    try:
        return ssl.create_default_context(cafile=ca_bundle.strip())
    except (OSError, ssl.SSLError):
        raise GitLabConfigError(
            "GITLAB_CA_BUNDLE não pôde ser lido como um bundle de certificados"
        ) from None


# --- Rate limit preventivo -------------------------------------------------


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        return int(float(value.strip()))
    except (ValueError, OverflowError):
        return None


def _seconds_until_reset(headers: httpx.Headers) -> float | None:
    """Segundos até o `RateLimit-Reset`, um epoch **absoluto** em segundos. None se ausente."""
    reset = _int_header(headers, "RateLimit-Reset")
    if reset is None:
        return None
    return min(max(reset - time.time(), 0.0), _MAX_RESET_WAIT_SECONDS)


def _retry_after(headers: httpx.Headers) -> float | None:
    """Segundos do `Retry-After` (número de segundos ou data HTTP). None se ausente ou inválido."""
    value = headers.get("Retry-After")
    if value is None:
        return None
    text = value.strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            when = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            return None
        seconds = when.timestamp() - time.time()
    if seconds != seconds:  # NaN
        return None
    return min(max(seconds, 0.0), _MAX_RESET_WAIT_SECONDS)


class _RateLimiter:
    """Janela deslizante de 60 s por instância (portanto por token).

    O limite efetivo é o menor entre o configurado e o `RateLimit-Limit`
    informado pelo GitLab. Se a API disser que não resta nenhuma requisição
    (`RateLimit-Remaining: 0`), novas requisições esperam até o `RateLimit-Reset`.
    """

    def __init__(self, per_minute: int, sleep: Sleep) -> None:
        if per_minute < 1:
            raise GitLabConfigError("GITLAB_RATE_LIMIT_PER_MINUTE deve ser pelo menos 1")
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
        # Só para baixo: o valor configurado é o teto.
        server_limit = _int_header(headers, "RateLimit-Limit")
        if server_limit is not None and server_limit > 0:
            self.limit = min(self._configured, server_limit)
        remaining = _int_header(headers, "RateLimit-Remaining")
        if remaining is not None and remaining <= 0:
            wait = _seconds_until_reset(headers)
            if wait is not None:
                self.block_for(wait)


# --- Paginação ----------------------------------------------------------------

_LINK_NEXT = re.compile(r'<([^>]*)>\s*;\s*rel="?next"?', re.IGNORECASE)


class _Reply(NamedTuple):
    data: Any
    headers: httpx.Headers


def _next_page(headers: httpx.Headers, current: int, size: int) -> int | None:
    """Próxima página, ou `None` se esta foi a última.

    Ordem: `X-Next-Page` (presente e vazio na última página), depois o
    `Link rel="next"`. Sem nenhum dos dois (um proxy pode removê-los), segue
    `page + 1` enquanto a página vier cheia. `X-Total` nunca é usado.
    """
    if "X-Next-Page" in headers:
        value = headers["X-Next-Page"].strip()
        if not value:
            return None
        try:
            return int(value)
        except ValueError:
            raise GitLabPaginationError("X-Next-Page não é um número") from None
    link = headers.get("Link")
    if link is not None:
        match = _LINK_NEXT.search(link)
        if match is None:
            return None
        pages = parse_qs(urlparse(match.group(1)).query).get("page")
        if not pages:
            raise GitLabPaginationError("Link rel=next sem o parâmetro `page`")
        try:
            return int(pages[0])
        except ValueError:
            raise GitLabPaginationError("Link rel=next com `page` inválido") from None
    return current + 1 if size >= PAGE_SIZE else None


# --- Cliente ---------------------------------------------------------------


def _bool(value: bool) -> str:
    return "true" if value else "false"


class GitLabClient:
    """Cliente somente leitura da API v4 do GitLab.

    Uma instância por token e por execução de sync:

        async with GitLabClient("https://gitlab.com", token) as client:
            async for page in client.iter_group_project_pages("123"):
                ...
    """

    def __init__(
        self,
        base_url: str,
        token: str | SecretStr,
        *,
        ca_bundle: str | None = None,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        max_attempts: int = MAX_ATTEMPTS,
        backoff_base_seconds: float = BACKOFF_BASE_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        secret = token if isinstance(token, SecretStr) else SecretStr(token)
        if not secret.get_secret_value().strip():
            raise GitLabConfigError("token do GitLab vazio")
        root = base_url.strip().rstrip("/")
        if not root.lower().startswith(("http://", "https://")):
            raise GitLabConfigError("GITLAB_URL deve começar com http:// ou https://")
        if root.endswith(API_PATH):
            root = root[: -len(API_PATH)]
        self._max_attempts = max(1, max_attempts)
        self._backoff_base = backoff_base_seconds
        self._sleep = sleep
        self._limiter = _RateLimiter(rate_limit_per_minute, sleep)
        self._host = urlparse(root).netloc
        self._http = httpx.AsyncClient(
            base_url=root + API_PATH,
            auth=_TokenAuth(secret),
            timeout=httpx.Timeout(TIMEOUT_SECONDS),
            headers={"Accept": "application/json"},
            verify=_ssl_context(ca_bundle),
            follow_redirects=False,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings, **kwargs: Any) -> Self:
        """Cliente do bot, com o limite de `GITLAB_RATE_LIMIT_PER_MINUTE` e o `GITLAB_CA_BUNDLE`."""
        if not settings.gitlab_url:
            raise GitLabConfigError("GITLAB_URL não está definido")
        if settings.gitlab_api_token is None:
            raise GitLabConfigError("GITLAB_API_TOKEN não está definido")
        kwargs.setdefault("rate_limit_per_minute", settings.gitlab_rate_limit_per_minute)
        kwargs.setdefault("ca_bundle", settings.gitlab_ca_bundle)
        return cls(settings.gitlab_url, settings.gitlab_api_token, **kwargs)

    def __repr__(self) -> str:
        return f"GitLabClient(host={self._host!r}, rate_limit_per_minute={self._limiter.limit})"

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- Endpoints de leitura ----------------------------------------------

    def iter_group_project_pages(self, group_id: str | int) -> AsyncIterator[GitLabPage[GitLabProject]]:
        """`GET /groups/:id/projects?include_subgroups=true&archived=false`, página a página."""
        return self._iter_pages(
            f"/groups/{quote_id(group_id)}/projects",
            [("include_subgroups", "true"), ("archived", _bool(False))],
            GitLabProject,
        )

    async def get_project(self, project_id: str | int) -> GitLabProject:
        """`GET /projects/:id`: um projeto avulso (`GITLAB_PROJECT_IDS`)."""
        path = f"/projects/{quote_id(project_id)}"
        reply = await self._get(path)
        return _parse(GitLabProject, reply.data, path)

    def iter_merge_request_pages(
        self, project_id: str | int, *, updated_after: datetime | None = None
    ) -> AsyncIterator[GitLabPage[GitLabMergeRequest]]:
        """`GET /projects/:id/merge_requests?state=all&scope=all[&updated_after=...]`.

        `updated_after` (com fuso) vira o instante ISO 8601 em UTC.
        """
        params: Params = [("state", "all"), ("scope", "all")]
        if updated_after is not None:
            params.append(("updated_after", format_instant(updated_after)))
        return self._iter_pages(
            f"/projects/{quote_id(project_id)}/merge_requests", params, GitLabMergeRequest
        )

    def iter_commit_pages(
        self, project_id: str | int, *, since: datetime | None = None
    ) -> AsyncIterator[GitLabPage[GitLabCommit]]:
        """`GET /projects/:id/repository/commits?all=true[&since=...]` (todos os branches).

        Um commit visto em vários branches vem uma vez por sha. `since` (com fuso)
        vira o instante ISO 8601 em UTC.
        """
        params: Params = [("all", "true")]
        if since is not None:
            params.append(("since", format_instant(since)))
        return self._iter_pages(
            f"/projects/{quote_id(project_id)}/repository/commits", params, GitLabCommit
        )

    async def _iter_pages[M: GitLabModel](
        self, path: str, base: Params, model: type[M]
    ) -> AsyncIterator[GitLabPage[M]]:
        """Pagina por offset (`per_page=100`), seguindo `X-Next-Page`; vazio = fim.

        Cada item é validado isoladamente: os inválidos vão para
        `GitLabPage.invalid` e não derrubam a página. Uma resposta que não seja
        uma lista levanta `GitLabResponseError`.

        Levanta `GitLabPaginationError` se uma página começar pelo mesmo item que
        a anterior, se a próxima página não avançar ou se passar de `MAX_PAGES`
        páginas. Nunca termina em silêncio nesses casos.
        """
        page = 1
        previous_first_id: str | None = None
        for _ in range(MAX_PAGES):
            reply = await self._get(path, [*base, ("per_page", str(PAGE_SIZE)), ("page", str(page))])
            items = reply.data
            if not isinstance(items, list):
                raise GitLabResponseError(f"GET {path}: resposta não é uma lista", path=path)
            if not items:
                return
            first_id = _raw_item_id(items[0])
            if first_id is not None and first_id == previous_first_id:
                raise GitLabPaginationError(
                    f"GET {path}: a página {page} repete a página anterior "
                    "(a API parece ignorar `page`)"
                )
            previous_first_id = first_id

            valid: list[M] = []
            invalid: list[InvalidItem] = []
            for item in items:
                try:
                    valid.append(model.model_validate(item))
                except ValidationError as exc:
                    invalid.append(InvalidItem(_raw_item_id(item), validation_reason(exc)))
            yield GitLabPage(page=page, items=valid, invalid=invalid, size=len(items))

            try:
                following = _next_page(reply.headers, page, len(items))
            except GitLabPaginationError as exc:
                raise GitLabPaginationError(f"GET {path}: {exc}") from None
            if following is None:
                return
            if following <= page:
                raise GitLabPaginationError(
                    f"GET {path}: a próxima página ({following}) não avança depois da {page}"
                )
            page = following
        raise GitLabPaginationError(
            f"GET {path}: mais de {MAX_PAGES} páginas; paginação interrompida"
        )

    # --- Núcleo: GET com rate limit e retries ------------------------------

    def _backoff(self, attempt: int) -> float:
        delay = self._backoff_base * (2 ** (attempt - 1))
        return delay + random.uniform(0, delay / 4)

    async def _get(self, path: str, params: Params | None = None) -> _Reply:
        """Faz um GET relativo a `/api/v4`. Único ponto de acesso à rede do cliente."""
        for attempt in range(1, self._max_attempts + 1):
            last_attempt = attempt == self._max_attempts
            await self._limiter.acquire()
            try:
                response = await self._http.get(path, params=params)
            except httpx.TimeoutException as exc:
                if last_attempt:
                    raise GitLabUnavailableError(
                        f"GET {path}: timeout após {self._max_attempts} tentativas",
                        status_code=None,
                        path=path,
                    ) from None
                reason = f"timeout ({type(exc).__name__})"
            except _TRANSIENT_NETWORK_ERRORS as exc:
                if isinstance(exc.__cause__, ssl.SSLError):
                    # Certificado recusado: repetir não resolve.
                    raise GitLabHTTPError(
                        f"GET {path}: falha de TLS ({type(exc.__cause__).__name__}); "
                        "confira GITLAB_URL e GITLAB_CA_BUNDLE",
                        status_code=None,
                        path=path,
                    ) from None
                if last_attempt:
                    raise GitLabUnavailableError(
                        f"GET {path}: erro de rede após {self._max_attempts} tentativas "
                        f"({type(exc).__name__})",
                        status_code=None,
                        path=path,
                    ) from None
                reason = f"erro de rede ({type(exc).__name__})"
            except httpx.RequestError as exc:
                # Não transitórios (DecodingError, TooManyRedirects, UnsupportedProtocol,
                # LocalProtocolError...): repetir não resolve. Sem retry.
                raise GitLabHTTPError(
                    f"GET {path}: falha na requisição ou na leitura da resposta "
                    f"({type(exc).__name__})",
                    status_code=None,
                    path=path,
                ) from None
            else:
                self._limiter.observe(response.headers)
                status = response.status_code

                if status < 300:
                    try:
                        return _Reply(response.json(), response.headers)
                    except ValueError:
                        raise GitLabHTTPError(
                            f"GET {path}: resposta {status} sem JSON válido",
                            status_code=status,
                            path=path,
                        ) from None

                if status == 401:
                    raise GitLabAuthError("token do bot inválido, expirado ou revogado")
                if status == 403:
                    raise GitLabForbiddenError(
                        f"GET {path}: 403 sem permissão{_error_detail(response)}",
                        status_code=status,
                        path=path,
                    )
                if status == 404:
                    raise GitLabNotFoundError(
                        f"GET {path}: 404 não encontrado{_error_detail(response)}",
                        status_code=status,
                        path=path,
                    )

                if status == 429:
                    if last_attempt:
                        raise GitLabRateLimitError(
                            f"GET {path}: 429 após {self._max_attempts} tentativas",
                            status_code=status,
                            path=path,
                        )
                    # O `Retry-After` manda; sem ele, o `RateLimit-Reset`. Piso de
                    # backoff: com o relógio local adiantado, o `Reset` pode já
                    # estar no passado, e as tentativas se esgotariam em segundos.
                    backoff = self._backoff(attempt)
                    advised = _retry_after(response.headers)
                    if advised is None:
                        advised = _seconds_until_reset(response.headers)
                    wait = backoff if advised is None else max(advised + random.uniform(0, 0.5), backoff)
                    # A espera fica no limitador: vale também para outras chamadas
                    # concorrentes com o mesmo token.
                    self._limiter.block_for(wait)
                    logger.warning(
                        "GitLab GET %s: 429; nova tentativa %d/%d em %.1fs",
                        path, attempt + 1, self._max_attempts, wait,
                    )
                    continue

                if status >= 500:
                    if last_attempt:
                        raise GitLabUnavailableError(
                            f"GET {path}: {status} após {self._max_attempts} tentativas",
                            status_code=status,
                            path=path,
                        )
                    reason = f"HTTP {status}"
                else:
                    raise GitLabHTTPError(
                        f"GET {path}: HTTP {status}{_error_detail(response)}",
                        status_code=status,
                        path=path,
                    )

            wait = self._backoff(attempt)
            logger.warning(
                "GitLab GET %s: %s; nova tentativa %d/%d em %.1fs",
                path, reason, attempt + 1, self._max_attempts, wait,
            )
            await self._sleep(wait)

        raise AssertionError("inalcançável")  # pragma: no cover


def _error_detail(response: httpx.Response) -> str:
    """Mensagem de erro do GitLab (`message` ou `error`), se o corpo for o JSON padrão."""
    try:
        body = response.json()
    except ValueError:
        return ""
    if not isinstance(body, dict):
        return ""
    message = body.get("message") or body.get("error")
    if not isinstance(message, str) or not message:
        return ""
    return f" ({message[:200]})"
