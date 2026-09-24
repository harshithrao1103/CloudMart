import os
import boto3
import base64
import json
import hashlib
import hmac
import time


# ============================================================
# AWS CLIENT
# ============================================================

ssm = boto3.client("ssm")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

AUTH_TOKEN_PARAMETER = os.environ["AUTH_TOKEN_PARAMETER"]
JWT_SECRET_PARAMETER = os.environ["JWT_SECRET_PARAMETER"]


# ============================================================
# GET SSM PARAMETER
# ============================================================

def get_ssm_parameter(parameter_name):

    response = ssm.get_parameter(
        Name=parameter_name,
        WithDecryption=True
    )

    return response["Parameter"]["Value"]


# ============================================================
# BASE64URL DECODE
# ============================================================

def base64url_decode(value):

    padding = "=" * (-len(value) % 4)

    return base64.urlsafe_b64decode(
        value + padding
    )


# ============================================================
# VERIFY JWT
# ============================================================

def verify_jwt(token):

    try:

        # ----------------------------------------------------
        # JWT must contain 3 parts
        # ----------------------------------------------------

        parts = token.split(".")

        if len(parts) != 3:

            print("Invalid JWT format")

            return None


        encoded_header = parts[0]
        encoded_payload = parts[1]
        encoded_signature = parts[2]


        # ----------------------------------------------------
        # Decode header
        # ----------------------------------------------------

        header_bytes = base64url_decode(
            encoded_header
        )

        header = json.loads(
            header_bytes.decode("utf-8")
        )


        # ----------------------------------------------------
        # Check algorithm
        # ----------------------------------------------------

        if header.get("alg") != "HS256":

            print("Unsupported JWT algorithm")

            return None


        # ----------------------------------------------------
        # Decode payload
        # ----------------------------------------------------

        payload_bytes = base64url_decode(
            encoded_payload
        )

        payload = json.loads(
            payload_bytes.decode("utf-8")
        )
        print("JWT payload:", payload)
        print("JWT exp:", payload.get("exp"))
        print("Current time:", int(time.time()))


        # ----------------------------------------------------
        # Get JWT secret
        # ----------------------------------------------------

        secret = get_ssm_parameter(
            JWT_SECRET_PARAMETER
        )


        # ----------------------------------------------------
        # Recreate signature
        # ----------------------------------------------------

        message = (
            f"{encoded_header}.{encoded_payload}"
        ).encode("utf-8")

        expected_signature = hmac.new(
            secret.encode("utf-8"),
            message,
            hashlib.sha256
        ).digest()

        provided_signature = base64url_decode(
            encoded_signature
        )


        # ----------------------------------------------------
        # Compare signatures
        # ----------------------------------------------------

        if not hmac.compare_digest(
            expected_signature,
            provided_signature
        ):
            print("JWT signature verification failed")
            print("Expected signature:", base64.urlsafe_b64encode(expected_signature).decode())
            print("Provided signature:", encoded_signature)



            return None


        # ----------------------------------------------------
        # Check expiration
        # ----------------------------------------------------

        expiration = payload.get("exp")

        if expiration is None:

            print("JWT expiration missing")

            return None


        if int(time.time()) >= int(expiration):

            print("JWT expired")

            return None


        # ----------------------------------------------------
        # Required subject
        # ----------------------------------------------------

        if not payload.get("sub"):

            print("JWT subject missing")

            return None


        # ----------------------------------------------------
        # Required role
        # ----------------------------------------------------

        if not payload.get("role"):

            print("JWT role missing")

            return None


        print(
            "JWT authentication successful for:",
            payload.get("email")
        )

        return payload


    except Exception as error:

        print(
            f"JWT verification error: {str(error)}"
        )

        return None


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    print("Authorizer Lambda started")

    try:

        # ====================================================
        # GET AUTHORIZATION HEADER
        # ====================================================

        headers = event.get("headers", {})

        authorization = (
            headers.get("authorization")
            or headers.get("Authorization")
        )

        if not authorization:

            print("Authorization header missing")

            return {
                "isAuthorized": False
            }


        # ====================================================
        # VALIDATE BEARER FORMAT
        # ====================================================

        if not authorization.startswith("Bearer "):

            print("Invalid Authorization header format")

            return {
                "isAuthorized": False
            }


        provided_token = authorization[7:].strip()

        if not provided_token:

            print("Bearer token is empty")

            return {
                "isAuthorized": False
            }


        # ====================================================
        # FIRST: CHECK ADMIN TOKEN
        # ====================================================

        expected_admin_token = get_ssm_parameter(
            AUTH_TOKEN_PARAMETER
        )

        if hmac.compare_digest(
            provided_token,
            expected_admin_token
        ):

            print("Admin authentication successful")

            return {
                "isAuthorized": True,
                "context": {
                    "userId": "admin",
                    "role": "admin"
                }
            }


        # ====================================================
        # SECOND: CHECK CUSTOMER JWT
        # ====================================================

        jwt_payload = verify_jwt(
            provided_token
        )

        if jwt_payload:

            print("Customer JWT authentication successful")

            return {
                "isAuthorized": True,
                "context": {
                    "userId": str(jwt_payload["sub"]),
                    "email": jwt_payload.get("email", ""),
                    "role": jwt_payload["role"]
                }
            }


        # ====================================================
        # AUTHENTICATION FAILED
        # ====================================================

        print("Authorization failed")

        return {
            "isAuthorized": False
        }


    except Exception as error:

        # ----------------------------------------------------
        # Fail closed if authentication infrastructure fails
        # ----------------------------------------------------

        print(
            f"Authorization error: {str(error)}"
        )

        return {
            "isAuthorized": False
        }
