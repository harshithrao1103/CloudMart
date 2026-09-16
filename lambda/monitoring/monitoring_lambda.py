import os
import boto3

cloudwatch = boto3.client("cloudwatch")

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")


def lambda_handler(event, context):
    cloudwatch.put_metric_data(
        Namespace="CloudMart/Operations",
        MetricData=[
            {
                "MetricName": "LowStockEvents",
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

    return {
        "statusCode": 200,
        "message": "LowStockEvents metric published"
    }