import json
import os
import boto3
import pymysql
import hashlib
import secrets
import base64


# ============================================================
# AWS CLIENTS
# ============================================================

ssm = boto3.client("ssm")


# ============================================================
# ENVIRONMENT VARIABLES
# ============================================================

RDS_HOST = os.environ["RDS_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]


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
# PASSWORD HASHING
# ============================================================

def hash_password(password):
    """
    Hash password using PBKDF2-HMAC-SHA256 with a random salt.
    """

    salt = secrets.token_bytes(16)

    password_hash = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        310000
    )

    encoded_salt = base64.b64encode(salt).decode("utf-8")
    encoded_hash = base64.b64encode(password_hash).decode("utf-8")

    return f"pbkdf2_sha256$310000${encoded_salt}${encoded_hash}"


# ============================================================
# GET USER ID FROM PATH
# ============================================================

def get_customer_id(event):

    path_parameters = event.get("pathParameters") or {}

    customer_id = path_parameters.get("customerId")

    if customer_id is None:
        return None

    try:

        customer_id = int(customer_id)

        if customer_id <= 0:
            return None

        return customer_id

    except (ValueError, TypeError):

        return None


# ============================================================
# CREATE CUSTOMER / USER
# ============================================================

def create_customer(event):

    try:

        body = json.loads(event.get("body") or "{}")
         if isinstance(body, str):
            body = json.loads(body)

    except json.JSONDecodeError:

        return response(
            400,
            {
                "message": "Invalid JSON request body"
            }
        )

    name = body.get("name")
    email = body.get("email")
    password = body.get("password")

    # --------------------------------------------------------
    # Validate input
    # --------------------------------------------------------

    if not name or not email or not password:

        return response(
            400,
            {
                "message": "name, email and password are required"
            }
        )

    if len(password) < 8:

        return response(
            400,
            {
                "message": "Password must be at least 8 characters"
            }
        )

    # --------------------------------------------------------
    # Hash password
    # --------------------------------------------------------

    password_hash = hash_password(password)

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Check whether email already exists
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT user_id
                FROM users
                WHERE email = %s
                """,
                (email,)
            )

            if cursor.fetchone():

                return response(
                    409,
                    {
                        "message": "User with email already exists"
                    }
                )

            # ------------------------------------------------
            # Create customer
            #
            # IMPORTANT:
            # Role is always customer.
            # The client cannot choose admin.
            # ------------------------------------------------

            cursor.execute(
                """
                INSERT INTO users
                    (name, email, password_hash, role, is_active)
                VALUES
                    (%s, %s, %s, 'customer', TRUE)
                """,
                (name, email, password_hash)
            )

            user_id = cursor.lastrowid

        connection.commit()

        return response(
            201,
            {
                "customer_id": user_id,
                "name": name,
                "email": email,
                "role": "customer"
            }
        )

    except pymysql.err.IntegrityError as error:

        connection.rollback()

        print(
            "Create customer integrity error:",
            str(error)
        )

        return response(
            409,
            {
                "message": "User with email already exists"
            }
        )

    except Exception as error:

        connection.rollback()

        print(
            "Create customer error:",
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
# GET CUSTOMER
# ============================================================

def get_customer(customer_id):

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    user_id,
                    name,
                    email,
                    role,
                    is_active,
                    created_at,
                    updated_at
                FROM users
                WHERE user_id = %s
                """,
                (customer_id,)
            )

            customer = cursor.fetchone()

        if not customer:

            return response(
                404,
                {
                    "message": "Customer not found"
                }
            )

        # ----------------------------------------------------
        # Do not return password_hash
        # ----------------------------------------------------

        return response(
            200,
            {
                "customer_id": customer["user_id"],
                "name": customer["name"],
                "email": customer["email"],
                "role": customer["role"],
                "is_active": customer["is_active"],
                "created_at": customer["created_at"].isoformat()
                if customer["created_at"] else None,
                "updated_at": customer["updated_at"].isoformat()
                if customer["updated_at"] else None
            }
        )

    except Exception as error:

        print(
            "Get customer error:",
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
# UPDATE CUSTOMER
# ============================================================

def update_customer(event, customer_id):

    try:
        print("RAW BODY:", repr(event.get("body")))
        body = json.loads(event.get("body") or "{}")
        if isinstance(body, str):
            body = json.loads(body)

    except json.JSONDecodeError:

        return response(
            400,
            {
                "message": "Invalid JSON request body"
            }
        )

    name = body.get("name")
    email = body.get("email")
    password = body.get("password")

    if not name or not email:

        return response(
            400,
            {
                "message": "name and email are required"
            }
        )

    # --------------------------------------------------------
    # Validate password if provided
    # --------------------------------------------------------

    if password is not None and len(password) < 8:

        return response(
            400,
            {
                "message": "Password must be at least 8 characters"
            }
        )

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Check user exists
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT user_id
                FROM users
                WHERE user_id = %s
                """,
                (customer_id,)
            )

            if not cursor.fetchone():

                return response(
                    404,
                    {
                        "message": "Customer not found"
                    }
                )

            # ------------------------------------------------
            # Check email is not used by another user
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT user_id
                FROM users
                WHERE email = %s
                  AND user_id <> %s
                """,
                (email, customer_id)
            )

            if cursor.fetchone():

                return response(
                    409,
                    {
                        "message":
                        "Email already belongs to another user"
                    }
                )

            # ------------------------------------------------
            # Update name and email
            # ------------------------------------------------

            if password:

                password_hash = hash_password(password)

                cursor.execute(
                    """
                    UPDATE users
                    SET
                        name = %s,
                        email = %s,
                        password_hash = %s
                    WHERE user_id = %s
                    """,
                    (
                        name,
                        email,
                        password_hash,
                        customer_id
                    )
                )

            else:

                cursor.execute(
                    """
                    UPDATE users
                    SET
                        name = %s,
                        email = %s
                    WHERE user_id = %s
                    """,
                    (
                        name,
                        email,
                        customer_id
                    )
                )

        connection.commit()

        return response(
            200,
            {
                "customer_id": customer_id,
                "name": name,
                "email": email
            }
        )

    except pymysql.err.IntegrityError as error:

        connection.rollback()

        print(
            "Update customer integrity error:",
            str(error)
        )

        return response(
            409,
            {
                "message":
                "Email already belongs to another user"
            }
        )

    except Exception as error:

        connection.rollback()

        print(
            "Update customer error:",
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
# DELETE CUSTOMER
# ============================================================

def delete_customer(customer_id):

    connection = get_db_connection()

    try:

        with connection.cursor() as cursor:

            # ------------------------------------------------
            # Check user exists
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT user_id
                FROM users
                WHERE user_id = %s
                """,
                (customer_id,)
            )

            if not cursor.fetchone():

                return response(
                    404,
                    {
                        "message": "Customer not found"
                    }
                )

            # ------------------------------------------------
            # Check whether customer has orders
            # ------------------------------------------------

            cursor.execute(
                """
                SELECT order_id
                FROM orders
                WHERE customer_id = %s
                LIMIT 1
                """,
                (customer_id,)
            )

            if cursor.fetchone():

                return response(
                    409,
                    {
                        "message":
                        "Customer cannot be deleted because "
                        "orders exist"
                    }
                )

            # ------------------------------------------------
            # Delete user
            # ------------------------------------------------

            cursor.execute(
                """
                DELETE FROM users
                WHERE user_id = %s
                """,
                (customer_id,)
            )

        connection.commit()

        return response(204)

    except Exception as error:

        connection.rollback()

        print(
            "Delete customer error:",
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

    print("Customer Lambda started")

    method = (
        event.get("httpMethod")
        or
        event.get("requestContext", {})
        .get("http", {})
        .get("method")
    )

    customer_id = get_customer_id(event)

    print("HTTP method:", method)
    print("Customer ID:", customer_id)

    # --------------------------------------------------------
    # POST /customers
    # --------------------------------------------------------

    if method == "POST" and customer_id is None:

        return create_customer(event)

    # --------------------------------------------------------
    # GET /customers/{customerId}
    # --------------------------------------------------------

    if method == "GET" and customer_id is not None:

        return get_customer(customer_id)

    # --------------------------------------------------------
    # PUT /customers/{customerId}
    # --------------------------------------------------------

    if method == "PUT" and customer_id is not None:

        return update_customer(
            event,
            customer_id
        )

    # --------------------------------------------------------
    # DELETE /customers/{customerId}
    # --------------------------------------------------------

    if method == "DELETE" and customer_id is not None:

        return delete_customer(customer_id)

    # --------------------------------------------------------
    # Unsupported request
    # --------------------------------------------------------

    return response(
        400,
        {
            "message": "Unsupported API request"
        }
    )