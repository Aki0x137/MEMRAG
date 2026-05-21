package aws

import (
	"context"
	"os"

	awsv2 "github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
)

func region() string {
	if value := os.Getenv("AWS_REGION"); value != "" {
		return value
	}
	if value := os.Getenv("AWS_DEFAULT_REGION"); value != "" {
		return value
	}
	return "us-east-1"
}

func LoadConfig(ctx context.Context) (awsv2.Config, error) {
	return awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(region()))
}
