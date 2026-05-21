package aws

import (
	"context"
	"fmt"
	"os"
	"strings"

	awsv2 "github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/secretsmanager"
)

func ResolveCredentialRef(ctx context.Context, credentialRef string) (string, error) {
	if credentialRef == "" {
		return "", fmt.Errorf("credential reference is required")
	}

	environment := strings.ToLower(os.Getenv("ENVIRONMENT"))
	if environment == "" || environment == "development" || environment == "test" {
		return credentialRef, nil
	}

	config, err := LoadConfig(ctx)
	if err != nil {
		return "", err
	}

	client := secretsmanager.NewFromConfig(config, func(options *secretsmanager.Options) {
		if endpoint := os.Getenv("AWS_SECRETS_MANAGER_ENDPOINT_URL"); endpoint != "" {
			options.BaseEndpoint = awsv2.String(endpoint)
		}
	})

	result, err := client.GetSecretValue(ctx, &secretsmanager.GetSecretValueInput{SecretId: awsv2.String(credentialRef)})
	if err != nil {
		return "", err
	}
	if result.SecretString == nil {
		return "", fmt.Errorf("secret %s has no string payload", credentialRef)
	}
	return *result.SecretString, nil
}
