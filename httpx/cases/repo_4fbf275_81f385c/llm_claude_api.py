"""
    with Client(
        cookies=cookies,
        proxies=proxies,
        cert=cert,
        verify=verify,
        timeout=timeout,
        trust_env=trust_env,
    ) as client:
        return client.request(
            method=method,
            url=url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            auth=auth,
            allow_redirects=allow_redirects,
        )


@contextmanager
def stream(
    method: str,
    url: URLTypes,
    *,
    params: QueryParamTypes = None,
    content: RequestContent = None,
    data: RequestData = None,
    files: RequestFiles = None,
    json: typing.Any = None,
    headers: HeaderTypes = None,
    cookies: CookieTypes = None,
    auth: AuthTypes = None,
    proxies: ProxiesTypes = None,
    timeout: TimeoutTypes = DEFAULT_TIMEOUT_CONFIG,
    allow_redirects: bool = True,
    verify: VerifyTypes = True,
    cert: CertTypes = None,
    trust_env: bool = True,
) -> typing.Iterator[Response]:
    """
    Alternative to `httpx.request()` that streams the response body
    instead of loading it into memory at once.

    **Parameters**: See `httpx.request`.

    See also: [Streaming Responses][0]

    [0]: /quickstart#streaming-responses
    """
    with Client(
        cookies=cookies, proxies=proxies, cert=cert, verify=verify, trust_env=trust_env
    ) as client:
        with client.stream(
            method=method,
            url=url,
            content=content,
            data=data,
            files=files,
            json=json,
            params=params,
            headers=headers,
            auth=auth,
            allow_redirects=allow_redirects,
            timeout=timeout,
        ) as response:
            yield response


def get(
    url: URLTypes,
    *,
    params: QueryParamTypes = None,
    headers: HeaderTypes = None,
    cookies: CookieTypes = None,
    auth: AuthTypes = None,
    proxies: ProxiesTypes = None,
    allow_redirects: bool = True,
    cert: CertTypes = None,
    verify: VerifyTypes = True,
    timeout: TimeoutTypes = DEFAULT_TIMEOUT_CONFIG,
    trust_env: bool = True,
) -> Response:
    """
    Sends a `GET` request.

    **Parameters**: See `httpx.request`.

    Note that the `data`, `files`, and `json` parameters are not available on
    this function, as `GET` requests should not include a request body.
    """
    return request(
        "GET",
        url,
        params=params,
        headers=headers,
        cookies=cookies,
        auth=auth,
        proxies=proxies,
        allow_redirects=allow_redirects,
        cert=cert,
        verify=verify,
        timeout=timeout,
        trust_env=trust_env,
    )


def options(
    url: URLTypes,
    *,
    params: QueryParamTypes = None,
    headers: HeaderTypes = None,
    cookies: CookieTypes = None,
    auth: AuthTypes = None,
    proxies: ProxiesTypes = None,
    allow_redirects: bool = True,
    cert: CertTypes = None,
    verify: VerifyTypes = True,
    timeout: TimeoutTypes = DEFAULT_TIMEOUT_CONFIG,
    trust_env: bool = True,
) -> Response:
    """
    Sends an `OPTIONS` request.

    **Parameters**: See `httpx.request`.

    Note that the `data`, `files`, and `json` parameters are not available on
    this function, as `OPTIONS` requests should not include a request body.
    """
    return request(
        "OPTIONS",
        url,
        params=params,
        headers=headers,
        cookies=cookies,
        auth=auth,
        proxies=proxies,
        allow_redirects=allow_redirects,
        cert=cert,
        verify=verify,
        timeout=timeout,
        trust_env=trust_env,
    )


def head(
    url: URLTypes,
    *,
    params: QueryParamTypes = None,
    headers: HeaderTypes = None,
    cookies: CookieTypes = None,
    auth: AuthTypes = None,
    proxies: ProxiesTypes = None,
    allow_redirects: bool = True,
    cert: CertTypes = None,
    verify: VerifyTypes = True,
    timeout: TimeoutTypes = DEFAULT_TIMEOUT_CONFIG,
    trust_env: bool = True,
) -> Response:
    """
    Sends a `HEAD` request.

    **Parameters**: See `httpx.request`.

    Note that the `data`, `files`, and `json` parameters are not available on
    this function, as `HEAD` requests should not include a request body.
    """
    return request(
        "HEAD",
        url,
        params=params,
        headers=headers,
        cookies=cookies,
        auth=auth,
        proxies=proxies,
        allow_redirects=allow_redirects,
        cert=cert,
        verify=verify,
        timeout=timeout,
        trust_env=trust_env,
    )


def post(
    url: URLTypes,
    *,
    content: RequestContent = None,
    data: RequestData = None,
    files: RequestFiles = None,
    json: typing.Any = None,
    params: QueryParamTypes = None,
    headers: HeaderTypes = None,
    cookies: CookieTypes = None,
    auth: AuthTypes = None,
    proxies: ProxiesTypes = None,
    allow_redirects: bool = True,
    cert: CertTypes = None,
    verify: VerifyTypes = True,
    timeout: TimeoutTypes = DEFAULT_TIMEOUT_CONFIG,
    trust_env: bool = True,
) -> Response:
    """
    Sends a `POST` request.

    **Parameters**: See `httpx.request`.
    """
    return request(
        "POST",
        url,
        content=content,
        data=data,
        files=files,
        json=json,
        params=params,
        headers=headers,
        cookies=cookies,
        auth=auth,
        proxies=proxies,
        allow_redirects=allow_redirects,
        cert=cert,
        verify=verify,
        timeout=timeout,
        trust_env=trust_env,
    )


def put(
    url: URLTypes,
    *,
    content: RequestContent = None,
    data: RequestData = None,
    files: RequestFiles = None,
    json: typing.Any = None,
    params: QueryParamTypes = None,
    headers: HeaderTypes = None,
    cookies: CookieTypes = None,
    auth: AuthTypes = None,
    proxies: ProxiesTypes = None,
    allow_redirects: bool = True,
    cert: CertTypes = None,
    verify: VerifyTypes = True,
    timeout: TimeoutTypes = DEFAULT_TIMEOUT_CONFIG,
    trust_env: bool = True,
) -> Response:
    """
    Sends a `PUT` request.

    **Parameters**: See `httpx.request`.
    """
    return request(
        "PUT",
        url,
        content=content,
        data=data,
        files=files,
        json=json,
        params=params,
        headers=headers,
        cookies=cookies,
        auth=auth,
        proxies=proxies,
        allow_redirects=allow_redirects,
        cert=cert,
        verify=verify,
        timeout=timeout,
        trust_env=trust_env,
    )


def patch(
    url: URLTypes,
    *,
    content: RequestContent = None,
    data: RequestData = None,
    files: RequestFiles = None,
    json: typing.Any = None,
    params: QueryParamTypes = None,
    headers: HeaderTypes = None,
    cookies: CookieTypes = None,
    auth: AuthTypes = None,
    proxies: ProxiesTypes = None,
    allow_redirects: bool = True,
    cert: CertTypes = None,
    verify: VerifyTypes = True,
    timeout: TimeoutTypes = DEFAULT_TIMEOUT_CONFIG,
    trust_env: bool = True,
) -> Response:
    """
    Sends a `PATCH` request.

    **Parameters**: See `httpx.request`.
    """
    return request(
        "PATCH",
        url,
        content=content,
        data=data,
        files=files,
        json=json,
        params=params,
        headers=headers,
        cookies=cookies,
        auth=auth,
        proxies=proxies,
        allow_redirects=allow_redirects,
        cert=cert,
        verify=verify,
        timeout=timeout,
        trust_env=trust_env,
    )


def delete(
    url: URLTypes,
    *,
    params: QueryParamTypes = None,
    headers: HeaderTypes = None,
    cookies: CookieTypes = None,
    auth: AuthTypes = None,
    proxies: ProxiesTypes = None,
    allow_redirects: bool = True,
    cert: CertTypes = None,
    verify: VerifyTypes = True,
    timeout: TimeoutTypes = DEFAULT_TIMEOUT_CONFIG,
    trust_env: bool = True,
) -> Response:
    """
    Sends a `DELETE` request.

    **Parameters**: See `httpx.request`.

    Note that the `data`, `files`, and `json` parameters are not available on
    this function, as `DELETE` requests should not include a request body.
    """
    return request(
        "DELETE",
        url,
        params=params,
        headers=headers,
        cookies=cookies,
        auth=auth,
        proxies=proxies,
        allow_redirects=allow_redirects,
        cert=cert,
        verify=verify,
        timeout=timeout,
        trust_env=trust_env,
    )