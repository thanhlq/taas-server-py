from http_fastapi.fastapi_msgspec.responses import MsgSpecJSONResponse
from http_fastapi.fastapi_msgspec.openapi import install_msgspec_openapi
from fastapi.responses import JSONResponse
from platform_core.http import AppConfig
from fastapi import FastAPI


def create_app(config: AppConfig, **kwargs) -> FastAPI:
    # 1. Important
    config.default_response_class = MsgSpecJSONResponse

    # 2. Create FastAPI app with custom settings
    app = FastAPI(
        default_response_class=config.default_response_class or JSONResponse,
        swagger_ui_parameters={
            'deepLinking': False,
            # OAuth2 redirect endpoint (automatically provided by FastAPI)
            'oauth2RedirectUrl': 'https://api.eworksuite.com/docs/oauth2-redirect',
            # Use PKCE for added security
            'usePkceWithAuthorizationCodeGrant': True,
        },
        # OAuth2 initialization parameters
        swagger_ui_init_oauth={
            'clientId': 'eworksuite-web',
            # "clientSecret": settings.KEYCLOAK_LOGIN_CLIENT_SECRET,  # Uncomment only if using confidential client
            'appName': f'{config.app_name} API Documentation',
            'scopes': 'openid profile email',
            'usePkceWithAuthorizationCodeGrant': True,
        },
        **kwargs,
    )

    # 3. Install MsgSpec OpenAPI support (must be after app creation)
    install_msgspec_openapi(app)

    # 4. Add a simple root endpoint for testing
    app.add_api_route(
        '/', lambda: {'message': f'Hello from {config.app_name}!'}, methods=['GET']
    )

    return app
