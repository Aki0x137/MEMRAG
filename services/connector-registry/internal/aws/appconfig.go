package aws

import (
	"context"
	"fmt"
	"os"

	awsv2 "github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/appconfigdata"
)

func LoadConnectorDefaults(ctx context.Context) ([]byte, error) {
	applicationID := os.Getenv("AWS_APP_CONFIG_APPLICATION_ID")
	environmentID := os.Getenv("AWS_APP_CONFIG_ENVIRONMENT_ID")
	profileID := os.Getenv("AWS_APP_CONFIG_PROFILE_ID")
	if applicationID == "" || environmentID == "" || profileID == "" {
		return nil, nil
	}

	config, err := LoadConfig(ctx)
	if err != nil {
		return nil, err
	}

	client := appconfigdata.NewFromConfig(config)
	session, err := client.StartConfigurationSession(ctx, &appconfigdata.StartConfigurationSessionInput{
		ApplicationIdentifier:          awsv2.String(applicationID),
		EnvironmentIdentifier:          awsv2.String(environmentID),
		ConfigurationProfileIdentifier: awsv2.String(profileID),
	})
	if err != nil {
		return nil, err
	}
	if session.InitialConfigurationToken == nil {
		return nil, fmt.Errorf("appconfig session returned no initial token")
	}

	output, err := client.GetLatestConfiguration(ctx, &appconfigdata.GetLatestConfigurationInput{
		ConfigurationToken: session.InitialConfigurationToken,
	})
	if err != nil {
		return nil, err
	}

	return output.Configuration, nil
}
