import os
import boto3


ssm = boto3.client("ssm")

AUTH_TOKEN_PARAMETER = os.environ["AUTH_TOKEN_PARAMETER"]


def lambda_handler(event, context):

    print("Authorizer Lambda started")

    try:

        # ==================================================
        # GET AUTHORIZATION HEADER
        # ==================================================

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


        # ==================================================
        # VALIDATE BEARER FORMAT
        # ==================================================

        if not authorization.startswith("Bearer "):

            print("Invalid Authorization header format")

            return {
                "isAuthorized": False
            }


        provided_token = authorization[7:]


        # ==================================================
        # GET EXPECTED TOKEN FROM SSM
        # ==================================================

        response = ssm.get_parameter(
            Name=AUTH_TOKEN_PARAMETER,
            WithDecryption=True
        )

        expected_token = response["Parameter"]["Value"]


        # ==================================================
        # COMPARE TOKENS
        # ==================================================

        if provided_token == expected_token:

            print("Authorization successful")

            return {
                "isAuthorized": True
            }


        print("Authorization failed")

        return {
            "isAuthorized": False
        }


    except Exception as error:

        # Fail closed if authentication infrastructure fails.
        print(
            f"Authorization error: {str(error)}"
        )

        return {
            "isAuthorized": False
        }