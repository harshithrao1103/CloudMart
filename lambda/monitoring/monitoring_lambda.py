import os
import boto3
from datetime import datetime, timezone

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


def publish_latency_metric(metric_name, event):
    event_time = event.get("time")

    if not event_time:
        return

    try:
        event_datetime = datetime.fromisoformat(
            event_time.replace("Z", "+00:00")
        )

        current_datetime = datetime.now(timezone.utc)

        latency_ms = (
            current_datetime - event_datetime
        ).total_seconds() * 1000

        if latency_ms < 0:
            latency_ms = 0

        cloudwatch.put_metric_data(
            Namespace="CloudMart/Operations",
            MetricData=[
                {
                    "MetricName": metric_name,
                    "Value": latency_ms,
                    "Unit": "Milliseconds",
                    "Dimensions": [
                        {
                            "Name": "Environment",
                            "Value": ENVIRONMENT
                        }
                    ]
                }
            ]
        )

    except Exception:
        pass


def lambda_handler(event, context):

    detail_type = event.get("detail-type")

    if detail_type == "OrderConfirmed":

        publish_metric("OrdersPlaced")

        publish_latency_metric(
            "OrdersPlacedLatency",
            event
        )

        return {
            "statusCode": 200,
            "message": "OrdersPlaced metric and latency published"
        }

    if detail_type == "OrderFailed":

        publish_metric("OrdersFailed")

        publish_latency_metric(
            "OrdersFailedLatency",
            event
        )

        return {
            "statusCode": 200,
            "message": "OrdersFailed metric and latency published"
        }

    if detail_type == "Inventory Changed":

        detail = event.get("detail", {})

        if detail.get("low_stock") is True:

            publish_metric("LowStockEvents")

            publish_latency_metric(
                "LowStockEventsLatency",
                event
            )

            return {
                "statusCode": 200,
                "message": "LowStockEvents metric and latency published"
            }

    return {
        "statusCode": 200,
        "message": "No monitoring metric required"
    }