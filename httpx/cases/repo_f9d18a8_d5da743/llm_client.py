import functools
import typing
import warnings
from types import TracebackType

import hstspreload

from .auth import Auth, AuthTypes, BasicAuth, FunctionAuth
from .backends.base import ConcurrencyBackend
from .config import (
    DEFAULT_MAX_REDIRECTS,
    DEFAULT_POOL_LIMITS,
    DEFAULT_TIMEOUT_CONFIG,
    UNSET,
    CertTypes,
    PoolLimits,
    Timeout,
    TimeoutTypes,
    UnsetType,
    VerifyTypes,
)
from .content_streams import ContentStream
from .dispatch.asgi import ASGIDispatch
from .dispatch.base import Dispatcher
from .dispatch.connection_pool import ConnectionPool
from .dispatch.proxy_http import HTTPProxy
from .exceptions import (
    HTTPError,
    InvalidURL,
    RedirectBodyUnavailable,
    RedirectLoop,
    TooManyRedirects,
)
from .models import (
    URL,
    Cookies,
    CookieTypes,
    Headers,
    HeaderTypes,
    ProxiesTypes,
    QueryParams,
    QueryParamTypes,
    Request,
    RequestData,
    RequestFiles,
    Response,
    URLTypes,
)
from .status_codes import codes
from .utils import ElapsedTimer, NetRCInfo, get_environment_proxies, get_logger

logger = get_logger(__name__)


class Client:
    """
    An HTTP client, with connection pooling, HTTP/2, redirects, cookie persistence, etc.

    Usage:

    ```
    >>> client = httpx.Client()
    >>> response = client.get('https://example.org')
    ```

    **Parameters:**

    * **auth** - *(optional)* An authentication class to use when sending
    requests.
    * **params** - *(optional)* Query parameters to include in request URLs, as
    a string, dictionary, or list of two-tuples.
    * **headers** - *(optional)* Dictionary of HTTP headers to include when
    sending requests.
    * **cookies** - *(optional)* Dictionary of Cookie items to include when
    sending requests.
    * **verify** - *(optional)* SSL certificates (a.k.a CA bundle) used to
    verify the identity of requested hosts. Either `True` (default CA bundle),
    a path to an SSL certificate file, or `False` (disable verification).
    * **cert** - *(optional)* An SSL certificate used by the requested host
    to authenticate the client. Either a path to an SSL certificate file, or
    two-tuple of (certificate file, key file), or a three-tuple of (certificate
    file, key file, password).
    * **http2** - *(optional)* A boolean indicating if HTTP/2 support should be
    enabled. Defaults to `False`.
    * **proxies** - *(optional)* A dictionary mapping HTTP protocols to proxy
    URLs.
    * **timeout** - *(optional)* The timeout configuration to use when sending
    requests.
    * **pool_limits** - *(optional)* The connection pool configuration to use
    when determining the maximum number of concurrently open HTTP connections.
    * **max_redirects** - *(optional)* The maximum number of redirect responses
    that should be followed.
    * **base_url** - *(optional)* A URL to use as the base when building
    request URLs.
    * **dispatch** - *(optional)* A dispatch class to use for sending requests
    over the network.
    * **app** - *(optional)* An ASGI application to send requests to,
    rather than sending actual network requests.
    * **backend** - *(optional)* A concurrency backend to use when issuing
    async requests. Either 'auto', 'asyncio', 'trio', or a `ConcurrencyBackend`
    instance. Defaults to 'auto', for autodetection.
    * **trust_env** - *(optional)* Enables or disables usage of environment
    variables for configuration.
    * **uds** - *(optional)* A path to a Unix domain socket to connect through.
    """

    def __init__(
        self,
        *,
        auth: AuthTypes = None,
        params: QueryParamTypes = None,
        headers: HeaderTypes = None,
        cookies: CookieTypes = None,
        verify: VerifyTypes = True,
        cert: CertTypes = None,
        http2: bool = False,
        proxies: ProxiesTypes = None,
        timeout: TimeoutTypes = DEFAULT_TIMEOUT_CONFIG,
        pool_limits: PoolLimits = DEFAULT_POOL_LIMITS,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        base_url: URLTypes = None,
        dispatch: Dispatcher = None,
        app: typing.Callable = None,
        backend: typing.Union[str, ConcurrencyBackend] = "auto",
        trust_env: bool = True,
        uds: str = None,
    ):
        if app is not None:
            dispatch = ASGIDispatch(app=app)

        if dispatch is None:
            dispatch = ConnectionPool(
                verify=verify,
                cert=cert,
                http2=http2,
                pool_limits=pool_limits,
                backend=backend,
                trust_env=trust_env,
                uds=uds,
            )

        if base_url is None:
            self.base_url = URL("", allow_relative=True)
        else:
            self.base_url = URL(base_url)

        if params is None:
            params = {}

        self.auth = auth
        self._params = QueryParams(params)
        self._headers = Headers(headers)
        self._cookies = Cookies(cookies)
        self.timeout = Timeout(timeout)
        self.max_redirects = max_redirects
        self.trust_env = trust_env
        self.dispatch = dispatch
        self.netrc = NetRCInfo()

        if proxies is None and trust_env:
            proxies = typing.cast(ProxiesTypes, get_environment_proxies())

        self.proxies: typing.Dict[str, Dispatcher] = _proxies_to_dispatchers(
            proxies,
            verify=verify,
            cert=cert,
            http2=http2,
            pool_limits=pool_limits,
            backend=backend,
            trust_env=trust_env,
        )

    @property
    def headers(self) -> Headers:
        """
        HTTP headers to include when sending requests.
        """
        return self._headers

    @headers.setter
    def headers(self, heade