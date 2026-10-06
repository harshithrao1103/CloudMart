# CloudMart

CloudMart is an AWS-hosted e-commerce application. The application uses
API Gateway and AWS Lambda for the API layer, Amazon RDS for MySQL for
application data, Amazon S3 for artifacts and generated reports, AWS
Systems Manager Parameter Store for runtime configuration and protected
values, EventBridge for application events and scheduled processing, SNS
for notifications, SQS for order-failure handling, CloudWatch for
observability, and an EC2-hosted Flask dashboard for administration.


## Key Features

- Customer registration and authentication
- Product management
- Product inventory management
- Order creation and management
- Order status lifecycle management
- Order cancellation and inventory restoration
- Customer order-item modification
- Admin dashboard
- Daily sales reporting
- S3-based report storage
- Event-driven notifications
- Order failure handling through SQS
- CloudWatch monitoring and alarms
- Environment-specific AWS deployments


## Prerequisites

- AWS account
- GitHub repository with GitHub Actions enabled
- AWS IAM role configured for GitHub OIDC
- AWS CLI
- Python
- Git
- Required GitHub repository/environment secrets



The infrastructure is defined with AWS CloudFormation and deployed
through GitHub Actions using AWS authentication through OIDC.

>
>
> **API invoke URL:** `<https://vdhy4gvqj3.execute-api.us-east-1.amazonaws.com/prod>`
>
> **Dashboard URL:** `<http://100.31.238.8/>`
>
> **AWS Region:** `US-EAST-1`
>
> **Environment:** `dev`, `test`, or `prod` as configured for the
> deployment.

------------------------------------------------------------------------



The EC2 dashboard authenticates with an administrator token and calls
the protected dashboard API endpoints. The dashboard also reads
generated daily reports from S3.

------------------------------------------------------------------------

## AWS Services

  -----------------------------------------------------------------------
  Service                             Purpose
  ----------------------------------- -----------------------------------
  Amazon API Gateway                  HTTP API entry point

  AWS Lambda                          Application and processing logic

  Lambda Authorizer                   Token validation and role/customer
                                      context

  Amazon RDS MySQL                    Application database

  Amazon S3                           Application artifacts and generated daily reports
                                      

  AWS Systems Manager Parameter Store Runtime configuration and protected
                                      parameters

  Amazon EventBridge                  Application events and scheduled
                                      daily reporting

  Amazon SNS                          Order, stock, and monitoring
                                       notifications


  Amazon EC2                          Flask administration dashboard

  Amazon CloudWatch                   Logs, custom metrics, dashboards,
                                      and alarms

  AWS IAM                             Service roles and permissions

  GitHub Actions                      CI/CD deployment
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## CloudFormation and Deployment Stacks

The deployment uses an application stack plus the Milestone 5 EC2 and
monitoring resources, along with supporting infrastructure stacks.

------------------------------------------------------------------------------------
Stack / Template                                      Responsibility
------------------------------------------------------ -----------------------------------
`cloudformation/Application_Stack.yaml`               API Gateway, authorizer, product,
                                                       customer, login, order,
                                                       notification, dashboard,
                                                       daily-report, and related
                                                       application resources

`cloudformation/Milestone5_EC2_Stack.yaml`            EC2 dashboard infrastructure

`cloudformation/Event_Monitoring_Stack.yaml`          CloudWatch dashboard, alarms, SNS
                                                       monitoring topics, and monitoring
                                                       integrations

`cloudformation/Network_Stack.yaml`                   Network infrastructure required
                                                       by the application

`cloudformation/Security_IAM_Stack.yaml`              IAM roles, permissions, security
                                                       groups, and security-related
                                                       infrastructure

`cloudformation/Storage_Database_Stack.yaml`          S3 storage and RDS MySQL database
                                                       resources
------------------------------------------------------------------------------------

The GitHub Actions workflow deploys the application infrastructure,
Milestone 5 EC2 infrastructure, monitoring resources, and finally
updates the dashboard application on the EC2 instance.
------------------------------------------------------------------------

## Repository Layout

``` text
.github/
  workflows/
    deploy.yaml

config/
  config.json

cloudformation/
  Application_Stack.yaml
  Milestone5_EC2_Stack.yaml
  Event _Monitoring _Stack.yaml
  Network_Stack.yaml
  Security_IAM_Stack.yaml
  Storage_Database_Stack.yaml

database/
  schema.sql

lambda/
  authorizer/
  product/
  customer/
  login/
  order/
  notification/
  dashboard/
  daily_report/
  order_processor/
  db_init/
  alarm_notification/

dashboard/
  app.py
  templates/
    login.html
    dashboard.html
```

------------------------------------------------------------------------

# Authentication and Authorization

CloudMart uses an API Gateway Lambda Authorizer for protected API
requests.

### Customer authentication

Customers use:

``` http
POST /login
```

The login route is configured without the API Gateway authorizer.

A successful customer login returns the customer authentication
token/JWT used for protected customer requests.

### Administrator authentication

The administrator uses the administrator token configured separately
from customer login. The administrator token is stored as a protected
SSM Parameter Store value.

The EC2 Flask dashboard asks for the administrator token and sends it
as:

``` http
Authorization: Bearer <admin-token>
```


------------------------------------------------------------------------

# API Endpoints

All routes below are the routes defined by the CloudFormation/API Lambda
implementation reviewed for this project.

The API base URL is:

``` text
<API_INVOKE_URL>
```

For example:

``` text
<API_INVOKE_URL>/products
```

Use the actual deployed API Gateway invoke URL in place of
`<API_INVOKE_URL>`.

------------------------------------------------------------------------

# Login API

## Customer API Calls

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/login` | Customer login |

## Admin API Calls

Admin does not use `/login`. The admin uses the configured administrator token.

---

# Product APIs

## Admin API Calls

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/products` | Create product |
| GET | `/products` | View all products |
| GET | `/products/{productId}` | View product |
| PUT | `/products/{productId}` | Update product |
| DELETE | `/products/{productId}` | Delete product |

## Customer API Calls

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/products` | View products |
| GET | `/products/{productId}` | View product |

Customers cannot create, update, or delete products.

---

# Customer APIs

## Admin API Calls

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/customers/{customerId}` | View customer |
| PUT | `/customers/{customerId}` | Update customer |
| DELETE | `/customers/{customerId}` | Deactivate customer |

## Customer API Calls

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/customers` | Register customer |
| GET | `/customers/{customerId}` | View customer |
| PUT | `/customers/{customerId}` | Update customer |
| DELETE | `/customers/{customerId}` | Deactivate customer |

`POST /customers` is the public customer registration route.

---

# Order APIs

## Admin API Calls

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/orders` | Create order |
| GET | `/orders/{orderId}` | View any order |
| GET | `/orders?customerId={customerId}` | View customer orders |
| PUT | `/orders/{orderId}` | Update order status |
| PATCH | `/orders/{orderId}` | Update order items |
| PATCH | `/orders/{orderId}/cancel` | Cancel order |

## Customer API Calls

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/orders` | Place an order |
| GET | `/orders/{orderId}` | View own order |
| GET | `/orders?customerId={customerId}` | View own orders |
| PATCH | `/orders/{orderId}` 
| PATCH | `/orders/{orderId}/cancel` 

Customer order access is restricted to the authenticated customer's own orders.
Admin can access any order.

---

# Dashboard APIs

## Admin API Calls

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/dashboard/products` | View product and inventory information |
| GET | `/dashboard/orders` | View recent orders |
| GET | `/dashboard/customers` | View customer information |

## Customer API Calls

No dashboard APIs are provided for customers. The dashboard is an admin-only interface.

---

# EC2 Flask Dashboard

The EC2 dashboard provides an administrative view of CloudMart.

The Flask application:

1.  Accepts the administrator token.
2.  Calls the dashboard product API.
3.  Calls the dashboard order API.
4.  Displays product inventory.
5.  Displays recent orders.
6.  Displays order-status counts.
7.  Calculates total sales excluding cancelled orders.
8.  Displays revenue information.
9.  Provides daily report status.
10. Provides access to generated S3 reports.
11. Provides customer information through the dashboard API.

The dashboard application is protected by an administrator login/token.

------------------------------------------------------------------------

# Daily Reports

The Daily Report Lambda is scheduled through EventBridge.

The reporting flow is:

``` text
EventBridge Schedule
        |
        v
Daily Report Lambda
        |
        v
RDS MySQL
        |
        v
Generate CSV
        |
        v
S3 Reports Bucket
        |
        v
EC2 Flask Dashboard
```

The report contains the daily order information and totals generated by
the Daily Report Lambda.

The dashboard can show the available report for a selected date and
provide access to the report stored in S3.

Previous reports remain available in the S3 reports bucket according to
the configured retention/storage behavior.

------------------------------------------------------------------------

# EventBridge and Notifications

Application events are published to EventBridge.

Order-related events include the configured order lifecycle events such
as:

``` text
OrderConfirmed
OrderProcessing
OrderShipped
OrderDelivered
OrderCancelled
OrderFailed
```

EventBridge rules route matching events to the configured notification
targets.

SNS is used for:

-   Order notifications
-   Low-stock notifications
-   Monitoring/alarm notifications

The order Lambda also sends failure information to the configured SQS
order-failure queue when an order-processing failure requires
failure-queue handling.

------------------------------------------------------------------------

# Monitoring and Observability

CloudMart uses CloudWatch for application and infrastructure monitoring.

The monitoring stack provides CloudWatch metrics, dashboards, logs, and
alarms.

Custom application metrics include:

``` text
OrdersPlaced
OrdersFailed
LowStockEvents
```

The monitoring dashboard also includes service-level information such as
API Gateway, Lambda, EC2, and RDS metrics.

Configured alarms include monitoring for areas such as:

-   Low-stock events
-   Failed orders
-   Order Lambda execution errors
-   Product Lambda throttles
-   RDS CPU utilization
-   EC2 CPU utilization
-   API Gateway 5XX errors

Alarm notifications are sent through SNS.


------------------------------------------------------------------------

# Database

CloudMart uses Amazon RDS for MySQL.

The database contains the application's core entities, including:

``` text
users
products
inventory
orders
order_items
order_history
```

The database initialization Lambda is used during deployment to
initialize the database schema.

------------------------------------------------------------------------

# Configuration and Secrets

Runtime configuration is stored outside the source code.

SSM Parameter Store is used for values such as:

``` text
/cloudmart/{environment}/db/password
/cloudmart/{environment}/auth/jwt-secret
/cloudmart/{environment}/auth/token
```

Secret values are stored using the configured protected parameter type.

GitHub Actions uses repository/environment secrets for
deployment-specific values.

Do not store secret values directly in:

-   Python source files
-   YAML templates
-   README files
-   GitHub repository files
-   CloudFormation outputs
-   API examples

------------------------------------------------------------------------

# Environment Separation

CloudMart supports environment-specific deployment.

The environment is passed to CloudFormation and resource names are
parameterized using the environment.

For example:

``` text
cloudmart-dev-...
cloudmart-test-...
cloudmart-prod-...
```

This keeps resources for different environments separate.

The same infrastructure templates can therefore be deployed for
different environments by changing the `Environment` parameter.

------------------------------------------------------------------------

# GitHub Actions Deployment

The deployment workflow uses GitHub Actions with AWS OIDC
authentication.

The deployment process includes:

``` text
Checkout
   |
   v
Configure AWS credentials
   |
   v
Validate templates
   |
   v
Build/package application
   |
   v
Deploy application
   |
   v
Initialize database
   |
   v
Deploy EC2 infrastructure
   |
   v
Deploy monitoring
   |
   v
Update EC2 dashboard application
```

The deployment workflow uses the configured AWS deployment role rather
than storing long-lived AWS access keys in the repository.

------------------------------------------------------------------------

# Deployment Verification

After deployment, verify:

### Admin API Calls

``` http
GET /dashboard/products
Authorization: Bearer <admin-token>
```

``` http
GET /dashboard/orders
Authorization: Bearer <admin-token>
```

``` http
GET /dashboard/customers
Authorization: Bearer <admin-token>
```

Expected result:

``` text
HTTP 200
```

### Customer API Calls

Login:

``` http
POST /login
```

Then use the returned customer token for protected customer operations.

Example:

``` http
GET /products
Authorization: Bearer <customer-token>
```

Example order:

``` http
POST /orders
Authorization: Bearer <customer-token>
```

Example customer orders:

``` http
GET /orders?customerId=<customer-id>
Authorization: Bearer <customer-token>
```

------------------------------------------------------------------------


# Teardown

Before deleting the environment:

1.  Back up any required RDS data.
2.  Preserve required S3 reports.
3.  Verify the target environment.
4.  Check CloudFormation stack dependencies.
5.  Delete resources through CloudFormation rather than manually
    deleting individual resources.

Delete dependent resources/stacks in the appropriate reverse dependency
order.

Do not manually remove individual resources simply to bypass a failed
CloudFormation stack.

------------------------------------------------------------------------

# Important API Summary

## Admin

``` text
Products
POST   /products
GET    /products
GET    /products/{productId}
PUT    /products/{productId}
DELETE /products/{productId}

Customers
GET    /customers/{customerId}
PUT    /customers/{customerId}
DELETE /customers/{customerId}

Orders
POST   /orders
GET    /orders/{orderId}
GET    /orders?customerId={customerId}
PUT    /orders/{orderId}
PATCH  /orders/{orderId}
PATCH  /orders/{orderId}/cancel

Dashboard
GET    /dashboard/products
GET    /dashboard/orders
GET    /dashboard/customers
```

## Customer

``` text
Authentication
POST   /login

Customer
POST   /customers
GET    /customers/{customerId}
PUT    /customers/{customerId}
DELETE /customers/{customerId}

Products
GET    /products
GET    /products/{productId}

Orders
POST   /orders
GET    /orders/{orderId}
GET    /orders?customerId={customerId}
PATCH  /orders/{orderId}
PATCH  /orders/{orderId}/cancel
```

## Public

``` text
POST /login
POST /customers
```

`POST /customers` and `POST /login` are configured as public
onboarding/authentication routes in the application stack.

------------------------------------------------------------------------

