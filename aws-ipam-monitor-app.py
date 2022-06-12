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
# AWS CLI reference: https://docs.aws.amazon.com/cli/latest/reference/ec2/get-ipam-resource-cidrs.html
# AWS Boto3 SDK reference: https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/ec2.html
# Lambda Best Practices reference: https://docs.aws.amazon.com/lambda/latest/dg/best-practices.html
# Lambda Developer reference: https://aws.amazon.com/blogs/architecture/best-practices-for-developing-on-aws-lambda/
# Lambda Python reference: https://docs.aws.amazon.com/lambda/latest/dg/lambda-python.html
# Lambda Python example https://github.com/awsdocs/aws-lambda-developer-guide/tree/main/sample-apps/blank-python
# Python reference: https://peps.python.org/pep-0008/
# requirements Python3.6+ (3.6-3.9)
# pip install --upgrade boto3

# IMPORTS
import boto3
import json
import os
import logging
import time
import sys
import math

# CONSTANTS
PAGE_SIZE_MIN = 100
PAGE_SIZE_MAX = 10000
DEFAULT_IPAM_RESOURCE_TYPE = "subnet"
DEFAULT_IPAM_SCOPE_TYPE = "private"
DEFAULT_IPAM_USAGE_THRESHOLD = 80.0
DEFAULT_IPAM_CLOUDWATCH_NAMESPACE = "CUSTOM/IPAM"
DEFAULT_IPAM_CLOUDWATCH_METRIC_PERCENTASSIGNED = "PercentAssigned"
DEFAULT_IPAM_CLOUDWATCH_METRIC_IPADDRESSAVAILABLE = "IpAddressAvailable"
DEFAULT_IPAM_CLOUDWATCH_METRIC_IPADDRESSTOTAL = "IpAddressTotal"
DEFAULT_IPAM_SNS_SUBJECT = 'IPAM Usage Alert'
DEFAULT_IPAM_RESOURCE_TYPES =[ "vpc", "subnet"]

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
    if (scopeResponse is not None):
        ipamScopes = scopeResponse['IpamScopes']
        for ipamScope in ipamScopes:
            if (ipamScope['IpamScopeType'] == ipamScopeType):
                myIpamScopeId = ipamScope['IpamScopeId']

    # get_ipam_resource_cidrs
    logger.info('Getting IPAM resource CIDRS: ' + ipamResourceType)

    # get_ipam_resource_cidrs from EC2 for specific scope ... results maybe paginated
    if (ipamResourceType == None or ipamResourceType == "*" or ipamResourceType == ""):
        # loop over defaults
        for defIpamResourceType in DEFAULT_IPAM_RESOURCE_TYPES:
            resourceCidrResponse = ec2.get_ipam_resource_cidrs(IpamScopeId=myIpamScopeId, ResourceType=defIpamResourceType, MaxResults=PAGE_SIZE_MAX)
            if (resourceCidrResponse is not None):
                allResourceCidrs += resourceCidrResponse['IpamResourceCidrs']            
    else:
        resourceCidrResponse = ec2.get_ipam_resource_cidrs(IpamScopeId=myIpamScopeId, ResourceType=ipamResourceType, MaxResults=PAGE_SIZE_MAX)
        if (resourceCidrResponse is not None):
            allResourceCidrs += resourceCidrResponse['IpamResourceCidrs']

    # evaluate resource CIDR vs. threshold
    for resourceCidr in allResourceCidrs:
        # multiply by 100 to get percent
        if ((resourceCidr['IpUsage'] * 100.0) > ipamUsageThreshold):
            myResourceCidrs.append(resourceCidr)
            # calculate cidr IpAddressTotal and IpAddressAvailable ... tested on IPv4
            # TODO handle IPv6 and arithmetic/string exceptions
            cidr = resourceCidr['ResourceCidr']
            cidrIpUsage = resourceCidr['IpUsage']
            idxSlash = cidr.index('/')
            cidrIpSize = int(cidr[idxSlash+1:])
            cidrIpAddressTotal = math.pow(2,(32-cidrIpSize))
            cidrIpAddressAvailable = (cidrIpAddressTotal * (1-cidrIpUsage))
            resourceCidr['IpAddressTotal'] = cidrIpAddressTotal
            resourceCidr['IpAddressAvailable'] = cidrIpAddressAvailable
    
    return myResourceCidrs

def send_sns_message(snsTopic, snsMessage, snsSubject=DEFAULT_IPAM_SNS_SUBJECT):

    logger.info("Sending SNS alert for IPAM CIDR resources")

    # sns
    sns = boto3.client("sns")

    # sns.publish
    sns_response = sns.publish( TopicArn=snsTopic, Subject=snsSubject, Message=snsMessage)

    return sns_response

def format_cloudwatch_metric_data_point(ipamResourceCidr, cwMetricName, cwMetricValue):
    # each CW metric data point has a Name, Value, Timestamp, and Dimensional Index by the ResourceId for uniqueness
    cw_metric_data_point = {}
    cw_metric_data_point['MetricName'] = cwMetricName
    cw_metric_data_point['Value'] = cwMetricValue
    cw_metric_data_point['Timestamp'] = time.time()
    cw_metric_data_point['Dimensions'] = [ { 'Name': 'ResourceId', 'Value': ipamResourceCidr['ResourceId']}]

    return cw_metric_data_point

def send_cloudwatch_metric(ipamResourceCidrs, cwNamespace=DEFAULT_IPAM_CLOUDWATCH_NAMESPACE):

    logger.info("Sending CloudWatch metric data for IPAM CIDR resources")

    # cloudwatch
    cw = boto3.client("cloudwatch")

    cw_metric_data_points = []

    for ipamResourceCidr in ipamResourceCidrs:
        # PercentAssigned ... IpUsage 
        cidrIpUsage = 100 * ipamResourceCidr['IpUsage']
        cw_metric_data_point_ipusage = format_cloudwatch_metric_data_point(ipamResourceCidr, DEFAULT_IPAM_CLOUDWATCH_METRIC_PERCENTASSIGNED, cidrIpUsage)
        cw_metric_data_points.append(cw_metric_data_point_ipusage)
        # IpAddressTotal
        cw_metric_data_point_iptotal = format_cloudwatch_metric_data_point(ipamResourceCidr, DEFAULT_IPAM_CLOUDWATCH_METRIC_IPADDRESSTOTAL, ipamResourceCidr['IpAddressTotal'])
        cw_metric_data_points.append(cw_metric_data_point_iptotal)
        # IpAddressAvailable
        cw_metric_data_point_ipavailable = format_cloudwatch_metric_data_point(ipamResourceCidr, DEFAULT_IPAM_CLOUDWATCH_METRIC_IPADDRESSAVAILABLE, ipamResourceCidr['IpAddressAvailable'])
        cw_metric_data_points.append(cw_metric_data_point_ipavailable)

    # attach CW NameSpace
    # cloudwatch.put_metric_data
    if (len(cw_metric_data_points) > 0):
        cw.put_metric_data(Namespace=cwNamespace, MetricData=cw_metric_data_points)

def format_ipam_cidr_resource_message(ipamResourceCidrs):
    ipam_cidr_resource_message = ''

    if (ipamResourceCidrs is not None):
        for ipamResourceCidr in ipamResourceCidrs:
            ipam_cidr_resource_message += ipamResourceCidr['ResourceId'] + ';' 
            ipam_cidr_resource_message += ipamResourceCidr['ResourceOwnerId'] + ";" 
            ipam_cidr_resource_message += str(100 * ipamResourceCidr['IpUsage']) + ";"
            ipam_cidr_resource_message += str(ipamResourceCidr['IpAddressTotal']) + ";"
            ipam_cidr_resource_message += str(ipamResourceCidr['IpAddressAvailable'])
            ipam_cidr_resource_message += ','

    return ipam_cidr_resource_message

# ENVIRONMENT VARIABLES 
# IPAM_USAGE_THRESHOLD : FLOAT
# IPAM_SCOPE_TYPE : public | private
# IPAM_RESOURCE_TYPE : vpc | subnet | eip | public-ipv4-pool | ipv6-pool
# IPAM_SNS_TOPIC
# IPAM_SNS_SUBJECT
# IPAM_CLOUDWATCH_ENABLED
# IPAM_CLOUDWATCH_NAMESPACE
# IPAM_CLOUDWATCH_METRIC
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
    
    if (myIpamResourceCidrs is None or len(myIpamResourceCidrs) <= 0):
        myResponseStatus = 200
        myResponseStatusMessage = "NO_IPAM_RESOURCE_CIDRS"

    # DEBUG.LOG
    for resourceCidr in myIpamResourceCidrs:
        logger.debug(resourceCidr)

    myResponseStatusMessage = format_ipam_cidr_resource_message(myIpamResourceCidrs)
    logger.debug(myResponseStatusMessage)

    # SNS
    ipamSnsTopic = None

    try:
        ipamSnsTopic = os.environ['IPAM_SNS_TOPIC']
        ipamSnsSubject = os.environ['IPAM_SNS_SUBJECT']

        if (ipamSnsTopic is not None and ipamSnsSubject != ''):
            send_sns_message(ipamSnsTopic, myResponseStatusMessage, ipamSnsSubject)

    except KeyError:
        logger.warn('Define Lambda Environment Variable: IPAM_SNS_TOPIC, IPAM_SNS_SUBJECT')
        # report, warn, and then ignore

    # CLOUDWATCH
    ipamCloudWatchNamespace = DEFAULT_IPAM_CLOUDWATCH_NAMESPACE

    try:
        ipamCloudWatchNamespace = os.environ['IPAM_CLOUDWATCH_NAMESPACE']
    except KeyError:
        logger.debug('Define Lambda Environment Variable: IPAM_CLOUDWATCH_NAMESPACE')
        # ignore

    try:
        ipamCloudWatcEnabled = str2bool(os.environ['IPAM_CLOUDWATCH_ENABLED'])
    
        if (ipamCloudWatcEnabled):
            send_cloudwatch_metric(myIpamResourceCidrs, ipamCloudWatchNamespace)

    except KeyError:
        logger.warn('Define Lambda Environment Variable: IPAM_CLOUDWATCH_ENABLED, IPAM_CLOUDWATCH_NAMESPACE')
        # report, warn, and then ignore

    return {
        "statusCode": myResponseStatus,
        "body": json.dumps({
            "Message": myResponseStatusMessage,
            "IpamResourceCidrs" : myIpamResourceCidrs
        })
    }

def str2bool(s):
    if (s != None):
        return s.lower() in ("yes", "y", "true", "t", "1")
    else:
        return False

##############################    
# CLI TEST
# main()
# ./aws-ipam-monitor-app.py --scope private --type vpc --snssubject "My IPAM Email Alert" --snstopic 'arn:aws:sns:us-east-2:1111111111:my-aws-sns-topic' --threshold 80.0
##############################  

if __name__ == '__main__':
    logger.setLevel(logging.INFO)

    myIpamScope = DEFAULT_IPAM_SCOPE_TYPE
    myIpamResourceType = DEFAULT_IPAM_RESOURCE_TYPE
    myIpamSnsTopic = None
    myIpamSnsSubject = DEFAULT_IPAM_SNS_SUBJECT
    myIpamIpUsageThreshold = 20.0

    args = sys.argv[1:]
    for i in range(0,len(args)):
        if (args[i] == "--scope"):
            myIpamScope = args[i+1]
        elif (args[i] == "--type"):
            myIpamResourceType = args[i+1]
        elif (args[i] == "--threshold"):
            myIpamIpUsageThreshold = float(args[i+1])
        elif (args[i] == "--topic"):
            myIpamSnsTopic = args[i+1]

    # init
    myIpamResourceCidrs = get_my_ipam_resource_cidrs(myIpamIpUsageThreshold, myIpamScope, myIpamResourceType)

    # create message
    myIpamResourceCidrMessage = format_ipam_cidr_resource_message(myIpamResourceCidrs)

    # DEBUG.LOG
    for resourceCidr in myIpamResourceCidrs:
        logger.info(resourceCidr)

    logger.info(myIpamResourceCidrMessage)

    # SNS
    if (myIpamSnsTopic is not None):
        send_sns_message(myIpamSnsTopic, myIpamResourceCidrMessage, myIpamSnsSubject)

    # CLOUDWATCH
    send_cloudwatch_metric(myIpamResourceCidrs)
