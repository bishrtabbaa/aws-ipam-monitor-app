"""
You must have an AWS account to use this Python code.
© 2022, Amazon Web Services, Inc. or its affiliates. All rights reserved.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

# file: aws-ipam-monitor-app.py
# author: bishrt@amazon.com
# date: 5-24-2022
# CLI reference: https://docs.aws.amazon.com/cli/latest/reference/ec2/get-ipam-resource-cidrs.html
# Boto3 reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html
# Lambda Best Practices reference: https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html
# Lambda Developer reference: https://aws.amazon.com/blogs/architecture/best-practices-for-developing-on-aws-lambda/
# Lambda Python reference: https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html
# Lambda Python example https://github.com/awsdocs/aws-lambda-developer-guide/tree/main/sample-apps/blank-python
# requirements Python3.6+ (3.6-3.9)
# pip install --upgrade boto3

# IMPORTS
from pickle import TRUE
import boto3
import json
import os
import logging
import time

# CONSTANTS
PAGE_SIZE_MIN = 100
PAGE_SIZE_MAX = 10000
DEFAULT_IPAM_RESOURCE_TYPE = "subnet"
DEFAULT_IPAM_SCOPE_TYPE = "private"
DEFAULT_IPAM_USAGE_THRESHOLD = 80.0
DEFAULT_IPAM_CLOUDWATCH_NAMESPACE = "CUSTOM/IPAM"
DEFAULT_IPAM_CLOUDWATCH_METRIC = "PercentAssigned"
DEFAULT_IPAM_SNS_SUBJECT = 'IPAM Usage Alert'

# LOGGER
logger = logging.getLogger()
# logger.handler == console
csh = logging.StreamHandler()
logger.addHandler(csh)
# logger.level
logger.setLevel(logging.INFO)

# ASSUME current runtime context has appropriate networking connectivity and IAM permissions in AWS account

def get_my_ipam_resource_cidrs(ipamUsageThreshold=DEFAULT_IPAM_USAGE_THRESHOLD, ipamScopeType=DEFAULT_IPAM_SCOPE_TYPE, ipamResourceType=DEFAULT_IPAM_RESOURCE_TYPE):

    # init local variables
    allResourceCidrs = []
    myResourceCidrs = []
    myIpamScopeId=''

    ec2 = boto3.client("ec2")

    # get_ipam_resource_cidrs
    logger.debug('Getting IPAM scopes')

    # get_ipam_scopes from EC2
    scopeResponse = ec2.describe_ipam_scopes(MaxResults=PAGE_SIZE_MIN)
    if (scopeResponse != None):
        ipamScopes = scopeResponse['IpamScopes']
        for ipamScope in ipamScopes:
            if (ipamScope['IpamScopeType'] == ipamScopeType):
                myIpamScopeId = ipamScope['IpamScopeId']

    # get_ipam_resource_cidrs
    logger.debug('Getting IPAM resource CIDRS')

    # get_ipam_resource_cidrs from EC2 for specific scope ... results maybe paginated
    resourceCidrResponse = ec2.get_ipam_resource_cidrs(IpamScopeId=myIpamScopeId, ResourceType=ipamResourceType, MaxResults=PAGE_SIZE_MAX)

    if (resourceCidrResponse != None):
        allResourceCidrs = resourceCidrResponse['IpamResourceCidrs']

    # evaluate resource CIDR vs. threshold
    for resourceCidr in allResourceCidrs:
        # multiply by 100 to get percent
        if ((resourceCidr['IpUsage'] * 100.0) > ipamUsageThreshold):
            myResourceCidrs.append(resourceCidr)
    
    return myResourceCidrs

def send_sns_message(snsTopic, snsMessage, snsSubject=DEFAULT_IPAM_SNS_SUBJECT):

    logger.info("Sending SNS alert for IPAM CIDR resources")

    # sns
    sns = boto3.client("sns")

    # sns.publish
    sns_response = sns.publish( TopicArn=snsTopic, Subject=snsSubject, Message=snsMessage)

    return sns_response

def format_cloudwatch_metric_data_point(ipamResourceCidr):
    cw_metric_data_point = {}
    cw_metric_data_point['MetricName'] = DEFAULT_IPAM_CLOUDWATCH_METRIC
    cw_metric_data_point['Timestamp'] = time.time()
    cw_metric_data_point['Value'] = 100 * ipamResourceCidr['IpUsage']
    cw_metric_data_point['Dimensions'] = [ { 'Name': 'ResourceId', 'Value': ipamResourceCidr['ResourceId']}]

    return cw_metric_data_point

def send_cloudwatch_metric(ipamResourceCidrs):

    logger.info("Sending CloudWatch metric data for IPAM CIDR resources")

    # cloudwatch
    cw = boto3.client("cloudwatch")

    cw_metric_data_points = []

    for ipamResourceCidr in ipamResourceCidrs:
        cw_metric_data_point = format_cloudwatch_metric_data_point(ipamResourceCidr)
        cw_metric_data_points.append(cw_metric_data_point)

    # cloudwatch.put_metric_data
    cw.put_metric_data(Namespace=DEFAULT_IPAM_CLOUDWATCH_NAMESPACE, MetricData=cw_metric_data_points)

def format_ipam_cidr_resource_message(ipamResourceCidrs):
    ipam_cidr_resource_message = ''

    if (ipamResourceCidrs != None):
        for ipamResourceCidr in ipamResourceCidrs:
            ipam_cidr_resource_message += ipamResourceCidr['ResourceId'] + ':' + ipamResourceCidr['ResourceOwnerId'] + ','

    return ipam_cidr_resource_message

# ENVIRONMENT VARIABLES 
# IPAM_USAGE_THRESHOLD : FLOAT
# IPAM_SCOPE_TYPE : public | private
# IPAM_RESOURCE_TYPE : vpc | subnet | eip | public-ipv4-pool | ipv6-pool
def lambda_handler(event, context):
    logger.debug('Getting OS environment variables.')

    # get OS environment variables ... and check-set with good defaults
    try:
        envIpamUsageThreshold = float(os.environ['IPAM_USAGE_THRESHOLD'])
    except KeyError:
        logger.warn('Define Lambda Environment Variable: IPAM_USAGE_THRESHOLD')
        envIpamUsageThreshold = DEFAULT_IPAM_USAGE_THRESHOLD
    
    try:
        envIpamScopeType = os.environ['IPAM_SCOPE_TYPE']
    except KeyError:
        logger.warn('Define Lambda Environment Variable: IPAM_SCOPE_TYPE')
        envIpamScopeType = DEFAULT_IPAM_SCOPE_TYPE
    
    try:
        envIpamResourceType = os.environ['IPAM_RESOURCE_TYPE']
    except KeyError:
        logger.warn('Define Lambda Environment Variable: IPAM_RESOURCE_TYPE')
        envIpamResourceType = DEFAULT_IPAM_RESOURCE_TYPE

    # get IPAM resource CIDRS
    myIpamResourceCidrs = get_my_ipam_resource_cidrs(envIpamUsageThreshold, envIpamScopeType, envIpamResourceType)
    myResponseStatusMessage = ''
    myResponseStatus = 200

    # create HTTP response status code and message
    
    if (myIpamResourceCidrs == None or len(myIpamResourceCidrs) <= 0):
        myResponseStatus = 500
        myResponseStatusMessage = "NO_IPAM_RESOURCE_CIDRS"

    # DEBUG.LOG
    for resourceCidr in myIpamResourceCidrs:
        logger.debug(resourceCidr)

    myResponseStatusMessage = format_ipam_cidr_resource_message(myIpamResourceCidrs)
    logger.debug(myResponseStatusMessage)

    # TODO ... action ... SNS, other Lambdas in a StepFunctionWorkflow
    ipamSnsTopic = None

    try:
        ipamSnsTopic = os.environ['IPAM_SNS_TOPIC']

        if (ipamSnsTopic != None):
            send_sns_message(ipamSnsTopic, myResponseStatusMessage)

    except KeyError:
        logger.info('Define Lambda Environment Variable: IPAM_SNS_TOPIC')
        # report, warn, and then ignore

    # TODO ... action ... CloudWatch metrics
    try:
        ipamCloudWatcEnabled = bool(os.environ['IPAM_CLOUDWATCH_ENABLED'])

        if (ipamCloudWatcEnabled):
            send_cloudwatch_metric(myIpamResourceCidrs)

    except KeyError:
        logger.info('Define Lambda Environment Variable: IPAM_CLOUDWATCH_ENABLED')
        # report, warn, and then ignore

    return {
        "statusCode": myResponseStatus,
        "body": json.dumps({
            "message": myResponseStatusMessage,
            "ipamResourceCidrs" : myIpamResourceCidrs
        })
    }


##############################    
# TEST
# main()
##############################  
logger.setLevel(logging.INFO)

# init
myIpamResourceCidrs = get_my_ipam_resource_cidrs(20.0, "private", "vpc")
myIpamResourceCidrMessage = ''
ipamSnsTopic = 'arn:aws:sns:us-east-2:645411899653:my-aws-training-email-bishrt'

# create message
myIpamResourceCidrMessage = format_ipam_cidr_resource_message(myIpamResourceCidrs)

# DEBUG.LOG
for resourceCidr in myIpamResourceCidrs:
    logger.info(resourceCidr)

logger.info(myIpamResourceCidrMessage)

# SNS
# send_sns_message(ipamSnsTopic, myIpamResourceCidrMessage)

# CLOUDWATCH
# send_cloudwatch_metric(myIpamResourceCidrs)

# TODO ... ACTION ... LAMBDA / STEPFUNCTION
