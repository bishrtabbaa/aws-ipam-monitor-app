# aws-ipam-monitor-app

## :globe_with_meridians: Amazon IPAM Overview

[Amazon IPAM](https://docs.aws.amazon.com/vpc/latest/ipam/what-it-is-ipam.html) is a VPC feature that makes it easier for you to plan, track, and monitor IP addresses for your AWS workloads. You can use IPAM's automated workflows to more efficiently manage IP addresses.

You can use IPAM to do the following:
- Organize IP address space into routing and security domains
- Monitor IP address space that's in use and monitor resources that are using space against business rules
- View the history of IP address assignments in your organization
- Automatically allocate CIDRs to VPCs using specific business rules
- Troubleshoot network connectivity issues
- Enable cross-region and cross-account sharing of your Bring Your Own IP (BYOIP) addresses

## Amazon VPC IPAM Examples

These examples provide an introduction to Amazon VPC IPAM and demonstrate how to integrate it into Lambda, SNS, CloudWatch, and other AWS services.

- [IPAM Monitor](aws-ipam-monitor-app.py) can be used to monitor IPAM CIDR resources, evaluate their IP usage, and then take downstream action if the usage exceeds a threshold.  It consists of a set of functions can be run in CLI mode, referenced as part of a larger program or within a standalone Lambda scheduled and integrates with other AWS services such as publishing alerts to SNS topics, sending metrics to CloudWatch, or passing information to other Lambda functions in a StepFunction workflow.
