import json
import boto3
import os

sns = boto3.client("sns")

MONITORING_TOPIC_ARN = os.environ["MONITORING_TOPIC_ARN"]


def lambda_handler(event, context):
    message = json.loads(event["Records"][0]["Sns"]["Message"])

    alarm_name = message.get("AlarmName", "")
    new_state = message.get("NewStateValue", "UNKNOWN")
    reason_data = message.get("NewStateReasonData", "{}")

    try:
        reason_data = json.loads(reason_data)
    except json.JSONDecodeError:
        reason_data = {}

    if "low-stock-events" in alarm_name:
        alarm_title = "Low Stock Events"
        metric_name = "LowStockEvents"
        threshold = 0
        threshold_text = "> 0"

    elif "orders-failed" in alarm_name:
        alarm_title = "Orders Failed"
        metric_name = "OrdersFailed"
        threshold = 0
        threshold_text = "> 0"

    elif "order-lambda-errors" in alarm_name:
        alarm_title = "Order Lambda Errors"
        metric_name = "Errors"
        threshold = 0
        threshold_text = "> 0"

    elif "rds-cpu" in alarm_name:
        alarm_title = "RDS CPU Utilization"
        metric_name = "CPUUtilization"
        threshold = 80
        threshold_text = "> 80%"

    else:
        alarm_title = alarm_name
        metric_name = reason_data.get("metricName", "Unknown")
        threshold = reason_data.get("threshold", 0)
        threshold_text = f"> {threshold}"

    evaluated_datapoints = reason_data.get("evaluatedDatapoints", [])

    if evaluated_datapoints:
        value = evaluated_datapoints[-1].get("value", 0)
    else:
        recent_datapoints = reason_data.get("recentDatapoints", [])
        value = recent_datapoints[-1] if recent_datapoints else 0

    if metric_name == "CPUUtilization":
        value_text = f"{value}%"
    else:
        value_text = str(value)

    message_text = f"""CLOUDMART ALERT

Alarm: {alarm_title}
Status: {new_state}

Metric: {metric_name}
Value: {value_text}
Threshold: {threshold_text}

Please check the CloudWatch monitoring dashboard and investigate the alert.

CloudMart Operations Monitoring
"""

    sns.publish(
        TopicArn=MONITORING_TOPIC_ARN,
        Message=message_text,
        Subject="CLOUDMART ALERT"
    )

    return {
        "statusCode": 200,
        "message": "Formatted alarm notification sent"
    }