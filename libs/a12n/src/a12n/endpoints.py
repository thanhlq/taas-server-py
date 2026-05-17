"""FastAPI routers for the IdP.

Wire this into your app:

    from fastapi import FastAPI
    from iam_oauth import OAuthServer
    from iam_oauth.endpoints import build_router

    app = FastAPI()
    oauth = OAuthServer(...)
    app.include_router(build_router(oauth))
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from iam_oauth.server import OAuthServer


def build_router(oauth: OAuthServer) -> APIRouter:
    router = APIRouter()

    # ------------------------------------------------------------------ OIDC
    @router.get('/.well-known/openid-configuration')
    async def discovery() -> JSONResponse:
        return JSONResponse(oauth.discovery_document())

    @router.get('/.well-known/jwks.json')
    async def jwks() -> JSONResponse:
        return JSONResponse(oauth.jwks.public_jwks())

    # ---------------------------------------------------------- OAuth core
    @router.get('/authorize')
    async def authorize(request: Request):
        # If the user is not authenticated in the IdP session, redirect to /login
        # preserving the original /authorize query string so we can resume.
        user = request.session.get('user_id')
        if not user:
            from urllib.parse import urlencode
            return RedirectResponse(
                url=f'/login?{urlencode({"next": str(request.url)})}'
            )
        return await oauth.server.create_authorization_response(request, grant_user=user)

    @router.post('/token')
    async def token(request: Request):
        return await oauth.server.create_token_response(request)

    @router.post('/introspect')
    async def introspect(request: Request):
        return await oauth.server.create_endpoint_response('introspection', request)

    @router.post('/revoke')
    async def revoke(request: Request):
        return await oauth.server.create_endpoint_response('revocation', request)

    @router.get('/userinfo')
    async def userinfo(request: Request):
        # Validate bearer token + return claims. Implementation depends on your
        # resource-server validator; left as TODO for app integration.
        raise HTTPException(status_code=501, detail='Wire ResourceProtector here')

    # ------------------------------------------------------------------ Login
    @router.get('/login', response_class=HTMLResponse)
    async def login_page(next: Optional[str] = None):
        # Render your branded login template here. Placeholder HTML below
        # offers the four authentication methods.
        return HTMLResponse(_LOGIN_HTML.format(next=next or ''))

    @router.post('/login/password')
    async def login_password(
        request: Request,
        email: str = Form(...),
        password: str = Form(...),
        next: str = Form(''),
    ):
        user = await oauth.user_repo.get_by_email(email)
        if user is None or not oauth.password_auth.verify(
            password_hash=user.password_hash, password=password
        ):
            raise HTTPException(status_code=401, detail='Invalid credentials')
        request.session['user_id'] = user.id
        return RedirectResponse(url=next or '/', status_code=303)

    @router.post('/login/magic/request')
    async def login_magic_request(
        request: Request,
        email: str = Form(...),
        next: str = Form(''),
    ):
        await oauth.magic_link_auth.request(
            email=email, next_url=next or None, base_url=str(request.base_url)
        )
        return JSONResponse({'status': 'sent'})

    @router.get('/login/magic/callback')
    async def login_magic_callback(request: Request, t: str = Query(...)):
        record = await oauth.magic_link_auth.consume(signed_token=t)
        user = await oauth.user_repo.get_by_email(record.email)
        if user is None:
            user = await oauth.user_repo.create(email=record.email)
        request.session['user_id'] = user.id
        return RedirectResponse(url=record.next_url or '/', status_code=303)

    # ---------------- Passkey ------------------------------------------------
    @router.post('/login/passkey/options')
    async def passkey_options(request: Request, email: Optional[str] = Form(None)):
        user = await oauth.user_repo.get_by_email(email) if email else None
        opts = await oauth.passkey_auth.begin_authentication(user=user)
        request.session['passkey_challenge'] = opts['challenge']
        return JSONResponse(opts)

    @router.post('/login/passkey/verify')
    async def passkey_verify(request: Request):
        payload = await request.json()
        challenge = request.session.pop('passkey_challenge', None)
        if not challenge:
            raise HTTPException(status_code=400, detail='No active challenge')
        cred = await oauth.passkey_auth.finish_authentication(
            expected_challenge=challenge.encode(), credential=payload['credential']
        )
        request.session['user_id'] = cred.user_id
        return JSONResponse({'status': 'ok', 'next': payload.get('next') or '/'})

    # ---------------- Federation --------------------------------------------
    @router.get('/login/federation/{provider}')
    async def federation_start(provider: str, request: Request, next: str = ''):
        client = oauth.federation.get(provider)
        redirect_uri = str(request.url_for('federation_callback', provider=provider))
        request.session['fed_next'] = next
        return await client.authorize_redirect(request, redirect_uri)

    @router.get('/login/federation/{provider}/callback', name='federation_callback')
    async def federation_callback(provider: str, request: Request):
        client = oauth.federation.get(provider)
        token = await client.authorize_access_token(request)
        userinfo = token.get('userinfo') or await client.parse_id_token(request, token)
        subject = userinfo['sub']
        email = userinfo.get('email')

        link = await oauth.federated_repo.get(provider, subject)
        if link is None:
            user = (await oauth.user_repo.get_by_email(email)) if email else None
            if user is None:
                user = await oauth.user_repo.create(email=email or f'{provider}:{subject}')
            await oauth.federated_repo.link(
                user_id=user.id, provider=provider, subject=subject, email=email
            )
            user_id = user.id
        else:
            user_id = link.user_id

        request.session['user_id'] = user_id
        return RedirectResponse(url=request.session.pop('fed_next', '/') or '/', status_code=303)

    return router


_LOGIN_HTML = """\
<!doctype html>
<html><head><title>Sign in</title></head>
<body>
  <h1>Sign in</h1>
  <form method="post" action="/login/password">
    <input type="hidden" name="next" value="{next}" />
    <input name="email" type="email" placeholder="Email" required />
    <input name="password" type="password" placeholder="Password" required />
    <button type="submit">Sign in with password</button>
  </form>
  <hr/>
  <form method="post" action="/login/magic/request">
    <input type="hidden" name="next" value="{next}" />
    <input name="email" type="email" placeholder="Email" required />
    <button type="submit">Email me a magic link</button>
  </form>
  <hr/>
  <button onclick="passkeyLogin()">Sign in with Passkey</button>
  <hr/>
  <a href="/login/federation/google?next={next}">Continue with Google</a> ·
  <a href="/login/federation/microsoft?next={next}">Continue with Microsoft</a> ·
  <a href="/login/federation/apple?next={next}">Continue with Apple</a>
</body></html>
"""
