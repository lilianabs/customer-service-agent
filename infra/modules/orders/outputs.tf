# Output value definitions

output "function_name" {
  description = "Name of the Lambda function."

  value = aws_lambda_function.orders_api.function_name
}

output "base_url" {
  description = "Base URL for the API Gateway stage."

  value = aws_apigatewayv2_stage.orders_api.invoke_url
}
