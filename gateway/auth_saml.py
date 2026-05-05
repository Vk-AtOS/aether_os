from flask import Flask, request, redirect, Response
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.settings import OneLogin_Saml2_Settings
import os
from typing import Dict, Any

app = Flask(__name__)

def get_saml_settings():
    return OneLogin_Saml2_Settings({
        "sp": {
            "entityId": os.environ.get("SAML_SP_ENTITY_ID"),
            "assertionConsumerService": {"url": os.environ.get("SAML_SP_ACS_URL")}
        },
        "idp": {
            "entityId": os.environ.get("SAML_IDP_ENTITY_ID"),
            "singleSignOnService": {"url": os.environ.get("SAML_IDP_SSO_URL")},
            "x509cert": os.environ.get("SAML_IDP_CERT")
        }
    })

@app.route("/auth/saml/metadata")
def metadata():
    settings = get_saml_settings()
    metadata = settings.get_sp_metadata()
    return Response(metadata, content_type='application/xml')

@app.route("/auth/saml/login")
def saml_login():
    auth = OneLogin_Saml2_Auth(request, get_saml_settings())
    return redirect(auth.login())

@app.route("/auth/saml/callback", methods=["POST"])
def saml_callback():
    auth = OneLogin_Saml2_Auth(request, get_saml_settings())
    auth.process_response()
    if auth.is_authenticated():
        # TODO: create/update user logic
        return "Authenticated", 200
    return "Error", 400
