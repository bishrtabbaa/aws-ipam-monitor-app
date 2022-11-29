# BASE IMAGE
FROM public.ecr.aws/lambda/python:3.9

# COPY artifacts
COPY aws-ipam-monitor-lib.py requirements.txt ./

# RUN and INSTALL Python dependencies
RUN python3.9 -m pip install -r requirements.txt -t .

# ENVIRONMENT
# ARG AWS_ACCESS_KEY_ID
# ARG AWS_SECRET_ACCESS_KEY
# ARG AWS_DEFAULT_REGION

# COMMAND
CMD ["aws-ipam-monitor-lib.lambda_handler"]