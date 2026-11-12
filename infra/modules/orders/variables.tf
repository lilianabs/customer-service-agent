# Input variable definitions

variable "aws_region" {
  description = "AWS region for all resources."

  type    = string
  default = "us-east-1"
}

variable "orders_bucket_name" {
  description = "Existing S3 bucket (created by scripts/create_infra.sh) that holds the orders data. Matches orders.bucket_name in config.json."

  type    = string
  default = "orders-service-db"
}

variable "orders_data_key" {
  description = "S3 object key of the orders data file."

  type    = string
  default = "orders.json"
}

variable "powertools_layer_arn" {
  description = "Powertools for AWS Lambda (Python) v3 public layer (Python 3.13, x86_64). Version 43 = Powertools 3.40.0."

  type    = string
  default = "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-x86_64:43"
}
