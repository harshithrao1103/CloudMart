from flask import Flask, render_template, request, redirect, session, url_for, Response
import requests
import boto3
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def format_ist_time(value):
    if not value:
        return ""

    if isinstance(value, str):
        value = datetime.fromisoformat(value)

    if value.tzinfo is None:
        value = value.replace(tzinfo=ZoneInfo("UTC"))

    return value.astimezone(IST).strftime("%Y-%m-%d %H:%M:%S")


app = Flask(__name__)

app.secret_key = "cloudmart-dashboard-secret"

API_URL = "https://0h8szqn3r5.execute-api.us-east-1.amazonaws.com/dev"
REPORTS_BUCKET = "cloudmart-dev-reports-598886663370"

s3 = boto3.client("s3")


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        token = request.form.get("token")
        #get token value from login

        if not token:
            return render_template(
                "login.html",
                error="Please enter admin token"
            )

        try:
            response = requests.get(
                f"{API_URL}/dashboard/products",
                headers={
                    "Authorization": f"Bearer {token}"
                },
                timeout=10
            )
        except requests.RequestException:
            return render_template(
                "login.html",
                error="Unable to connect to CloudMart API"
            )

        if response.status_code == 200:
            session["admin_token"] = token
            return redirect(url_for("dashboard"))

        return render_template(
            "login.html",
            error="Invalid admin token"
        )

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    token = session.get("admin_token")

    if not token:
        return redirect(url_for("login"))

    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        products_response = requests.get(
            f"{API_URL}/dashboard/products",
            headers=headers,
            timeout=10
        )

        orders_response = requests.get(
            f"{API_URL}/dashboard/orders",
            headers=headers,
            timeout=10
        )

    except requests.RequestException:
        return "Unable to connect to CloudMart API.", 502

    if products_response.status_code == 401:
        session.clear()
        return redirect(url_for("login"))

    if products_response.status_code != 200:
        return "Unable to load products.", 502

    if orders_response.status_code != 200:
        return "Unable to load orders.", 502

    products = products_response.json().get(
        "products",
        []
    )

    orders = orders_response.json().get(
        "orders",
        []
    )

    for order in orders:
        order["created_at"] = format_ist_time(
            order.get("created_at")
        )
    reports = get_previous_reports()
    return render_template(
        "dashboard.html",
        products=products,
        orders=orders,
        reports=reports
    )
@app.route("/api/customers")
def customers():
    token = session.get("admin_token")

    if not token:
        return {
            "message": "Unauthorized"
        }, 401

    try:
        response = requests.get(
            f"{API_URL}/dashboard/customers",
            headers={
                "Authorization": f"Bearer {token}"
            },
            timeout=10
        )

    except requests.RequestException:
        return {
            "message": "Unable to connect to CloudMart API"
        }, 502

    if response.status_code == 401:
        session.clear()
        return {
            "message": "Unauthorized"
        }, 401

    return (
        response.text,
        response.status_code,
        {
            "Content-Type": "application/json"
        }
    )


@app.route("/api/customer/<customer_id>")
def customer(customer_id):
    token = session.get("admin_token")

    if not token:
        return {
            "message": "Unauthorized"
        }, 401

    try:
        response = requests.get(
            f"{API_URL}/dashboard/customers",
            params={
                "customer_id": customer_id
            },
            headers={
                "Authorization": f"Bearer {token}"
            },
            timeout=10
        )

    except requests.RequestException:
        return {
            "message": "Unable to connect to CloudMart API"
        }, 502

    if response.status_code == 401:
        session.clear()
        return {
            "message": "Unauthorized"
        }, 401

    return (
        response.text,
        response.status_code,
        {
            "Content-Type": "application/json"
        }
    )


def get_previous_reports():
    try:
        response = s3.list_objects_v2(
            Bucket=REPORTS_BUCKET,
            Prefix="daily-report-"
        )

        reports = []

        for obj in response.get("Contents", []):
            key = obj["Key"]
            #fileame/path
            if key.startswith("daily-report-") and key.endswith(".csv"):
                date_part = key.replace("daily-report-", "").replace(".csv", "")

                try:
                    report_date = datetime.strptime(date_part, "%Y-%m-%d").date()

                    reports.append({
                        "date": report_date.strftime("%d-%m-%Y"),
                        "key": key
                    })

                except ValueError:
                    continue

        reports.sort(
            key=lambda report: datetime.strptime(
                report["date"], "%d-%m-%Y"
            ),
            reverse=True
        )

        return reports

    except Exception as e:
        print("Error fetching previous reports:", e)
        return []


def get_today_report_key():
    today = datetime.now(IST).date().isoformat()
    return f"daily-report-{today}.csv"


def get_report_url(download=False):
    key = get_today_report_key()

    try:
        s3.head_object(
            Bucket=REPORTS_BUCKET,
            Key=key
        )
    except s3.exceptions.ClientError:
        return None

    response = s3.generate_presigned_url(
        #head_object() checks the S3 object without downloading the file.
        "get_object",
        Params={
            "Bucket": REPORTS_BUCKET,
            "Key": key,
            "ResponseContentType": "text/csv"
        },
        ExpiresIn=300
    )

    return response


@app.route("/report/view")
def view_report():
    if not session.get("admin_token"):
        return redirect(url_for("login"))

    url = get_report_url()

    if not url:
        return "Today's report is not available yet.", 404

    return redirect(url)


@app.route("/report/download")
def download_report():
    if not session.get("admin_token"):
        return redirect(url_for("login"))

    key = get_today_report_key()

    try:
        s3.head_object(
            Bucket=REPORTS_BUCKET,
            Key=key
        )
    except s3.exceptions.ClientError:
        return "Today's report is not available yet.", 404

    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": REPORTS_BUCKET,
            "Key": key,
            "ResponseContentType": "text/csv",
            "ResponseContentDisposition": f'attachment; filename="{key}"'
        },
        ExpiresIn=300
    )

    return redirect(url)


@app.route("/report/download/<report_date>")
def download_previous_report(report_date):
    if not session.get("admin_token"):
        return redirect(url_for("login"))

    try:
        report_date_obj = datetime.strptime(
            report_date,
            "%d-%m-%Y"
        )

        key = f"daily-report-{report_date_obj.strftime('%Y-%m-%d')}.csv"

    except ValueError:
        return "Invalid report date.", 400

    try:
        s3.head_object(
            Bucket=REPORTS_BUCKET,
            Key=key
        )
    except s3.exceptions.ClientError:
        return "Report is not available.", 404

    url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": REPORTS_BUCKET,
            "Key": key,
            "ResponseContentType": "text/csv",
            "ResponseContentDisposition": f'attachment; filename="{key}"'
            #This tells the browser to download the CSV rather than open it.
        },
        ExpiresIn=300
    )

    return redirect(url)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=8000
    )