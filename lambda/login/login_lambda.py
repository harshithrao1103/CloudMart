import json
import os
import boto3
import pymysql
import hashlib
import hmac
import base64
import time


# ============================================================
# AWS CLIENT
# ============================================================

ssm = boto3.client("ssm")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

RDS_HOST = os.environ["RDS_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]

JWT_SECRET_PARAMETER = os.environ["JWT_SECRET_PARAMETER"]


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_db_connection():

    response = ssm.get_parameter(
        Name=DB_PASSWORD_PARAMETER,
        WithDecryption=True
    )

    db_password = response["Parameter"]["Value"]

    return pymysql.connect(
        host=RDS_HOST,
        user=DB_USER,
        password=db_password,
        database=DB_NAME,
        port=3306,
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor
    )


# ============================================================
# HTTP RESPONSE
# ============================================================

def response(status_code, body=None):

    result = {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json"
        }
    }

    if body is not None:
        result["body"] = json.dumps(body)

    return result


# ============================================================
# BASE64URL ENCODING
# ============================================================

def base64url_encode(data):

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


# ============================================================
# PASSWORD VERIFICATION
# ============================================================

def verify_password(password, stored_hash):

    try:

        parts = stored_hash.split("$")

        if len(parts) != 4:
            return False

        algorithm = parts[0]
        iterations = int(parts[1])
        encoded_salt = parts[2]
        encoded_hash = parts[3]

        if algorithm != "pbkdf2_sha256":
            return False

        salt = base64.b64decode(encoded_salt)
        expected_hash = base64.b64decode(encoded_hash)

        calculated_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations
        )

        return hmac.compare_digest(
            calculated_hash,
            expected_hash
        )

    except Exception as error:

        print(
            "Password verification error:",
            str(error)
        )

        return False


# ============================================================
# GET JWT SECRET FROM SSM
# ============================================================

def get_jwt_secret():

    response = ssm.get_parameter(
        Name=JWT_SECRET_PARAMETER,
        WithDecryption=True
    )

    return response["Parameter"]["Value"]


# ============================================================
# CREATE JWT
# ============================================================

def create_jwt(user_id, email, role):

    secret = get_jwt_secret()

    # --------------------------------------------------------
    # JWT Header
    # --------------------------------------------------------

    header = {
        "alg": "HS256",
        "typ": "JWT"
    }

    # --------------------------------------------------------
    # JWT Payload
    # --------------------------------------------------------

    now = int(time.time())

    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": now,
        "exp": now + 3600
    }

    # --------------------------------------------------------
    # Encode header and payload
    # --------------------------------------------------------

    header_json = json.dumps(
        header,
        separators=(",", ":")
    ).encode("utf-8")

    payload_json = json.dumps(
        payload,
        separators=(",", ":")
    ).encode("utf-8")

    encoded_header = base64url_encode(header_json)
    encoded_payload = base64url_encode(payload_json)

    message = (
        f"{encoded_header}.{encoded_payload}"
    ).encode("utf-8")

    # --------------------------------------------------------
    # Create HMAC SHA256 signature
    # --------------------------------------------------------

    signature = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256
    ).digest()

    encoded_signature = base64url_encode(signature)

    # --------------------------------------------------------
    # Final JWT
    # --------------------------------------------------------

    token = (
        f"{encoded_header}."
        f"{encoded_payload}."
        f"{encoded_signature}"
    )

    return token


# ============================================================
# LOGIN
# ============================================================

def login_user(event):

    try:

        body = json.loads(
            event.get("body") or "{}"
        )
        if isinstance(body, str):
            body = json.loads(body)

    except json.JSONDecodeError:

        return response(
            400,
            {
                "message": "Invalid JSON request body"
            }
        )

    email = body.get("email")
    password = body.get("password")

    # --------------------------------------------------------
    # Validate input
    # --------------------------------------------------------

    if not email or not password:

        return response(
            400,
            {
                "message": "email and password are required"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Find user
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT
                    user_id,
                    name,
                    email,
                    password_hash,
                    role,
                    is_active
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            user = cursor.fetchone()

        # ----------------------------------------------------
        # User not found
        # ----------------------------------------------------

        if not user:

            return response(
                401,
                {
                    "message": "Invalid email or password"
                }
            )

        # ----------------------------------------------------
        # Check active status
        # ----------------------------------------------------

        if not user["is_active"]:

            return response(
                403,
                {
                    "message": "User account is inactive"
                }
            )

        # ----------------------------------------------------
        # Check password
        # ----------------------------------------------------

        if not user["password_hash"]:

            return response(
                401,
                {
                    "message": "Invalid email or password"
                }
            )

        password_valid = verify_password(
            password,
            user["password_hash"]
        )

        if not password_valid:

            return response(
                401,
                {
                    "message": "Invalid email or password"
                }
            )

        # ----------------------------------------------------
        # Create JWT
        # ----------------------------------------------------

        access_token = create_jwt(
            user["user_id"],
            user["email"],
            user["role"]
        )

        # ----------------------------------------------------
        # Return token
        # ----------------------------------------------------

        return response(
            200,
            {
                "message": "Login successful",
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 3600,
                "user": {
                    "user_id": user["user_id"],
                    "name": user["name"],
                    "email": user["email"],
                    "role": user["role"]
                }
            }
        )

    except Exception as error:

        print(
            "Login error:",
            str(error)
        )

        return response(
            500,
            {
                "message": "Internal server error"
            }
        )

    finally:

        connection.close()


# ============================================================
# LAMBDA HANDLER
# ============================================================

def lambda_handler(event, context):

    print("Login Lambda started")

    method = (
        event.get("httpMethod")
        or
        event.get("requestContext", {})
        .get("http", {})
        .get("method")
    )

    print("HTTP method:", method)

    # --------------------------------------------------------
    # POST /login
    # --------------------------------------------------------

    if method == "POST":

        return login_user(event)

    # --------------------------------------------------------
    # Unsupported request
    # --------------------------------------------------------

    return response(
        400,
        {
            "message": "Unsupported API request"
        }
    )