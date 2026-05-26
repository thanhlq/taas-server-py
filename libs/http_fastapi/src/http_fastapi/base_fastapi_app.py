from fastapi import FastAPI


def build_app(**kwargs) -> FastAPI:
    app = FastAPI(
        # default_response_class=kwargs.get("default_response_class", ORJSONResponse),

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
            'appName': 'eWorkSuite API Documentation',
            'scopes': 'openid profile email',
            'usePkceWithAuthorizationCodeGrant': True,
        },
        **kwargs
    )

    app.add_api_route("/hello", lambda: {"message": "Hello from FastAPI!"}, methods=["GET"])

    return app
