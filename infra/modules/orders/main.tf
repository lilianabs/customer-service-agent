provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project = "customer-service-assistant"
      module  = "orders"
    }
  }
}

locals {
  # API Gateway route keys, one per Lambda endpoint.
  routes = [
    "GET /orders/{order_number}",
    "GET /orders/{order_number}/return-policy",
    "GET /orders/{order_number}/refund-status",
    "GET /orders/{order_number}/refund-amount",
    "POST /orders/{order_number}/refund",
    "GET /inventory/{product_code}",
  ]
}

# --- Lambda package -----------------------------------------------------------
# Order data is read from the S3 bucket created by scripts/create_infra.sh,
# so the local mock data is not bundled. Powertools comes from a public layer.

data "archive_file" "lambda_orders_api" {
  type = "zip"

  source_dir  = "${path.module}/../../../services/orders"
  output_path = "${path.module}/build/orders.zip"

  excludes = ["__pycache__", "mock_data", "code.zip"]
}

resource "aws_lambda_function" "orders_api" {
  function_name = "orders-api"

  filename         = data.archive_file.lambda_orders_api.output_path
  source_code_hash = data.archive_file.lambda_orders_api.output_base64sha256

  runtime       = "python3.13"
  handler       = "lambda_function.lambda_handler"
  architectures = ["x86_64"]
  layers        = [var.powertools_layer_arn]

  role    = aws_iam_role.lambda_exec.arn
  timeout = 30

  environment {
    variables = {
      ORDERS_BUCKET           = var.orders_bucket_name
      ORDERS_KEY              = var.orders_data_key
      POWERTOOLS_SERVICE_NAME = "orders"
      POWERTOOLS_LOG_LEVEL    = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.orders_api]
}

resource "aws_cloudwatch_log_group" "orders_api" {
  name              = "/aws/lambda/orders-api"
  retention_in_days = 30
}

# --- IAM ----------------------------------------------------------------------

resource "aws_iam_role" "lambda_exec" {
  name = "orders-lambda-exec"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_orders_data" {
  name = "orders-data-read"
  role = aws_iam_role.lambda_exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = "arn:aws:s3:::${var.orders_bucket_name}/${var.orders_data_key}"
    }]
  })
}

# --- API Gateway (HTTP API) ---------------------------------------------------

resource "aws_apigatewayv2_api" "orders_api" {
  name          = "orders-api"
  protocol_type = "HTTP"
}

resource "aws_cloudwatch_log_group" "api_gw" {
  name              = "/aws/api_gw/${aws_apigatewayv2_api.orders_api.name}"
  retention_in_days = 30
}

resource "aws_apigatewayv2_stage" "orders_api" {
  api_id      = aws_apigatewayv2_api.orders_api.id
  name        = "v1"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_gw.arn

    format = jsonencode({
      requestId               = "$context.requestId"
      sourceIp                = "$context.identity.sourceIp"
      requestTime             = "$context.requestTime"
      protocol                = "$context.protocol"
      httpMethod              = "$context.httpMethod"
      resourcePath            = "$context.resourcePath"
      routeKey                = "$context.routeKey"
      status                  = "$context.status"
      responseLength          = "$context.responseLength"
      integrationErrorMessage = "$context.integrationErrorMessage"
    })
  }
}

resource "aws_apigatewayv2_integration" "orders_api" {
  api_id = aws_apigatewayv2_api.orders_api.id

  integration_uri        = aws_lambda_function.orders_api.invoke_arn
  integration_type       = "AWS_PROXY"
  integration_method     = "POST"
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "orders_api" {
  for_each = toset(local.routes)

  api_id    = aws_apigatewayv2_api.orders_api.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.orders_api.id}"
}

resource "aws_lambda_permission" "api_gw" {
  statement_id  = "AllowExecutionFromAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.orders_api.function_name
  principal     = "apigateway.amazonaws.com"

  source_arn = "${aws_apigatewayv2_api.orders_api.execution_arn}/*/*"
}
