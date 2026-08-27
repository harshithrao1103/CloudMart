# import json
# import os
# import boto3
# import pymysql

# ssm = boto3.client("ssm")

# RDS_HOST = os.environ["RDS_HOST"]
# DB_NAME = os.environ["DB_NAME"]
# DB_USER = os.environ["DB_USER"]
# DB_PASSWORD_PARAMETER = os.environ["DB_PASSWORD_PARAMETER"]


# def get_db_connection():

#     response = ssm.get_parameter(
#         Name=DB_PASSWORD_PARAMETER,
#         WithDecryption=True
#     )

#     db_password = response["Parameter"]["Value"]

#     return pymysql.connect(
#         host=RDS_HOST,
#         user=DB_USER,
#         password=db_password,
#         database=DB_NAME,
#         port=3306,
#         connect_timeout=10,
#         cursorclass=pymysql.cursors.DictCursor
#     )


# def response(status_code, body=None):

#     result = {
#         "statusCode": status_code,
#         "headers": {
#             "Content-Type": "application/json"
#         }
#     }

#     if body is not None:
#         result["body"] = json.dumps(body)

#     return result


# def get_customer_id(event):

#     path_parameters = event.get("pathParameters") or {}

#     customer_id = path_parameters.get("customerId")

#     if customer_id is None:
#         return None

#     try:

#         customer_id = int(customer_id)

#         if customer_id <= 0:
#             return None

#         return customer_id

#     except (ValueError, TypeError):

#         return None


# def create_customer(event):

#     try:

#         body = json.loads(event.get("body") or "{}")

#     except json.JSONDecodeError:

#         return response(
#             400,
#             {"message": "Invalid JSON request body"}
#         )

#     name = body.get("name")
#     email = body.get("email")

#     if not name or not email:

#         return response(
#             400,
#             {
#                 "message": "name and email are required"
#             }
#         )

#     connection = get_db_connection()

#     try:

#         with connection.cursor() as cursor:

#             # Check whether email already exists
#             cursor.execute(
#                 """
#                 SELECT customer_id
#                 FROM customers
#                 WHERE email = %s
#                 """,
#                 (email,)
#             )

#             if cursor.fetchone():

#                 return response(
#                     409,
#                     {
#                         "message":
#                         "Customer with email already exists"
#                     }
#                 )

#             # Create customer
#             cursor.execute(
#                 """
#                 INSERT INTO customers
#                     (name, email)
#                 VALUES
#                     (%s, %s)
#                 """,
#                 (name, email)
#             )

#             customer_id = cursor.lastrowid

#         connection.commit()

#         return response(
#             201,
#             {
#                 "customer_id": customer_id,
#                 "name": name,
#                 "email": email
#             }
#         )

#     except pymysql.err.IntegrityError as error:

#         connection.rollback()

#         print("Create customer integrity error:", str(error))

#         return response(
#             409,
#             {
#                 "message":
#                 "Customer with email already exists"
#             }
#         )

#     except Exception as error:

#         connection.rollback()

#         print("Create customer error:", str(error))

#         return response(
#             500,
#             {
#                 "message": "Internal server error"
#             }
#         )

#     finally:

#         connection.close()


# def get_customer(customer_id):

#     connection = get_db_connection()

#     try:

#         with connection.cursor() as cursor:

#             cursor.execute(
#                 """
#                 SELECT
#                     customer_id,
#                     name,
#                     email,
#                     created_at
#                 FROM customers
#                 WHERE customer_id = %s
#                 """,
#                 (customer_id,)
#             )

#             customer = cursor.fetchone()

#         if not customer:

#             return response(
#                 404,
#                 {
#                     "message": "Customer not found"
#                 }
#             )

#         return response(
#             200,
#             customer
#         )

#     except Exception as error:

#         print("Get customer error:", str(error))

#         return response(
#             500,
#             {
#                 "message": "Internal server error"
#             }
#         )

#     finally:

#         connection.close()


# def update_customer(event, customer_id):

#     try:

#         body = json.loads(event.get("body") or "{}")

#     except json.JSONDecodeError:

#         return response(
#             400,
#             {
#                 "message": "Invalid JSON request body"
#             }
#         )

#     name = body.get("name")
#     email = body.get("email")

#     if not name or not email:

#         return response(
#             400,
#             {
#                 "message": "name and email are required"
#             }
#         )

#     connection = get_db_connection()

#     try:

#         with connection.cursor() as cursor:

#             # Check customer exists
#             cursor.execute(
#                 """
#                 SELECT customer_id
#                 FROM customers
#                 WHERE customer_id = %s
#                 """,
#                 (customer_id,)
#             )

#             if not cursor.fetchone():

#                 return response(
#                     404,
#                     {
#                         "message": "Customer not found"
#                     }
#                 )

#             # Check email is not used by another customer
#             cursor.execute(
#                 """
#                 SELECT customer_id
#                 FROM customers
#                 WHERE email = %s
#                   AND customer_id <> %s
#                 """,
#                 (email, customer_id)
#             )

#             if cursor.fetchone():

#                 return response(
#                     409,
#                     {
#                         "message":
#                         "Email already belongs to another customer"
#                     }
#                 )

#             # Update customer
#             cursor.execute(
#                 """
#                 UPDATE customers
#                 SET
#                     name = %s,
#                     email = %s
#                 WHERE customer_id = %s
#                 """,
#                 (name, email, customer_id)
#             )

#         connection.commit()

#         return response(
#             200,
#             {
#                 "customer_id": customer_id,
#                 "name": name,
#                 "email": email
#             }
#         )

#     except pymysql.err.IntegrityError as error:

#         connection.rollback()

#         print("Update customer integrity error:", str(error))

#         return response(
#             409,
#             {
#                 "message":
#                 "Email already belongs to another customer"
#             }
#         )

#     except Exception as error:

#         connection.rollback()

#         print("Update customer error:", str(error))

#         return response(
#             500,
#             {
#                 "message": "Internal server error"
#             }
#         )

#     finally:

#         connection.close()


# def delete_customer(customer_id):

#     connection = get_db_connection()

#     try:

#         with connection.cursor() as cursor:

#             # Check customer exists
#             cursor.execute(
#                 """
#                 SELECT customer_id
#                 FROM customers
#                 WHERE customer_id = %s
#                 """,
#                 (customer_id,)
#             )

#             if not cursor.fetchone():

#                 return response(
#                     404,
#                     {
#                         "message": "Customer not found"
#                     }
#                 )

#             # Check whether customer has orders
#             cursor.execute(
#                 """
#                 SELECT order_id
#                 FROM orders
#                 WHERE customer_id = %s
#                 LIMIT 1
#                 """,
#                 (customer_id,)
#             )

#             if cursor.fetchone():

#                 return response(
#                     409,
#                     {
#                         "message":
#                         "Customer cannot be deleted because "
#                         "orders exist"
#                     }
#                 )

#             # Delete customer
#             cursor.execute(
#                 """
#                 DELETE FROM customers
#                 WHERE customer_id = %s
#                 """,
#                 (customer_id,)
#             )

#         connection.commit()

#         return response(204)

#     except Exception as error:

#         connection.rollback()

#         print("Delete customer error:", str(error))

#         return response(
#             500,
#             {
#                 "message": "Internal server error"
#             }
#         )

#     finally:

#         connection.close()


# def lambda_handler(event, context):

#     print("Customer Lambda started")

#     method = (
#         event.get("httpMethod")
#         or
#         event.get("requestContext", {})
#         .get("http", {})
#         .get("method")
#     )

#     customer_id = get_customer_id(event)

#     print("HTTP method:", method)
#     print("Customer ID:", customer_id)

#     # POST /customers
#     if method == "POST" and customer_id is None:

#         return create_customer(event)

#     # GET /customers/{customerId}
#     if method == "GET" and customer_id is not None:

#         return get_customer(customer_id)

#     # PUT /customers/{customerId}
#     if method == "PUT" and customer_id is not None:

#         return update_customer(event, customer_id)

#     # DELETE /customers/{customerId}
#     if method == "DELETE" and customer_id is not None:

#         return delete_customer(customer_id)

#     return response(
#         400,
#         {
#             "message": "Unsupported API request"
#         }
#     )