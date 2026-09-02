import json
import boto3
import os

ses = boto3.client("ses")

SENDER_EMAIL = os.environ["SENDER_EMAIL"]


def lambda_handler(event, context):
    print("Received EventBridge event:")
    print(json.dumps(event))

    detail = event.get("detail", {})

    event_type = event.get("detail-type", "OrderEvent")

    customer_email = detail.get("customer_email")
    order_id = detail.get("order_id")

    if not customer_email:
        print("Customer email not found in event")
        return {
            "statusCode": 400,
            "body": json.dumps({
                "message": "Customer email is missing"
            })
        }

    subject = f"CloudMart Order #{order_id} - {event_type}"

    body = f"""
Hello,

Your CloudMart order #{order_id} has been updated.

Order event: {event_type}

Thank you for shopping with CloudMart.

Regards,
CloudMart Team
"""

    response = ses.send_email(
        Source=SENDER_EMAIL,
        Destination={
            "ToAddresses": [customer_email]
        },
        Message={
            "Subject": {
                "Data": subject
            },
            "Body": {
                "Text": {
                    "Data": body
                }
            }
        }
    )

    print(f"Email sent successfully to {customer_email}")
    print(f"SES Message ID: {response['MessageId']}")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "message": "Notification email sent successfully",
            "message_id": response["MessageId"]
        })
    }