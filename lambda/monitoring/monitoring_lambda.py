import os
import boto3

cloudwatch = boto3.client("cloudwatch")

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")


def publish_metric(metric_name):
    cloudwatch.put_metric_data(
        Namespace="CloudMart/Operations",
        MetricData=[
            {
                "MetricName": metric_name,
                "Value": 1,
                "Unit": "Count",
                "Dimensions": [
                    {
                        "Name": "Environment",
                        "Value": ENVIRONMENT
                    }
                ]
            }
        ]
    )


def lambda_handler(event, context):

    detail_type = event.get("detail-type")

    if detail_type == "OrderCreated":
        publish_metric("OrdersPlaced")

        return {
            "statusCode": 200,
            "message": "OrdersPlaced metric published"
        }

    if detail_type == "Inventory Changed":
        detail = event.get("detail", {})

        if detail.get("low_stock") is True:
            publish_metric("LowStockEvents")

            return {
                "statusCode": 200,
                "message": "LowStockEvents metric published"
            }

    return {
        "statusCode": 200,
        "message": "No monitoring metric required"
    }