import json
import os

import boto3
import pymysql


# ==================================================
# ENVIRONMENT VARIABLES
# ==================================================

RDS_HOST = os.environ["RDS_HOST"]
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]


# ==================================================
# AWS CLIENTS
# ==================================================

ssm = boto3.client("ssm")


# ==================================================
# GET DATABASE PASSWORD
# ==================================================

def get_db_password():
    response = ssm.get_parameter(
        Name=DB_PASSWORD_PARAMETER,
        WithDecryption=True
    )

    return response["Parameter"]["Value"]


# ==================================================
# DATABASE CONNECTION
# ==================================================

def get_connection():
    return pymysql.connect(
        host=RDS_HOST,
        user=DB_USER,
        password=get_db_password(),
        database=DB_NAME,
        port=3306,
        connect_timeout=10,
        cursorclass=pymysql.cursors.DictCursor
    )


# ==================================================
# LAMBDA HANDLER
# ==================================================

def lambda_handler(event, context):

    print("Database initialization Lambda started")

    connection = None

    try:

        # --------------------------------------------------
        # Read schema.sql packaged with this Lambda
        # --------------------------------------------------

        schema_path = os.path.join(
            os.path.dirname(__file__),
            "schema.sql"
        )

        print("Reading schema.sql")

        with open(schema_path, "r", encoding="utf-8") as file:
            schema = file.read()

        # --------------------------------------------------
        # Connect to RDS
        # --------------------------------------------------

        print("Connecting to RDS")

        connection = get_connection()

        print("Connected to RDS successfully")

        # --------------------------------------------------
        # Execute SQL statements
        # --------------------------------------------------

        with connection.cursor() as cursor:

            statements = [
                statement.strip()
                for statement in schema.split(";")
                if statement.strip()
            ]

            print(f"Executing {len(statements)} SQL statements")

            for statement in statements:
                cursor.execute(statement)

        # --------------------------------------------------
        # Commit changes
        # --------------------------------------------------

        connection.commit()

        print("Database schema initialized successfully")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Database initialized successfully"
            })
        }

    except Exception as error:

        print(
            f"Database initialization error: "
            f"{type(error).__name__}: {error}"
        )

        if connection:
            connection.rollback()

        # Make Lambda invocation fail
        raise

    finally:

        if connection:
            connection.close()

        print("Database initialization Lambda finished")