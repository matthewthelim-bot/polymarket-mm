#!/usr/bin/env bash
# CloudWatch alerting + auto-healing for the collector instance.
#
# HOW TO RUN (2 minutes, no local AWS CLI needed):
#   1. Log in to the AWS console -> click the CloudShell icon (>_ in the top bar)
#   2. Paste this whole file, press Enter
#   3. Click the confirmation link in the email AWS sends you
#
# What it creates:
#   - SNS topic "polymarket-ec2-alerts" emailing matthewthelim@gmail.com
#   - Alarm 1: SYSTEM status check fail (AWS hardware/network fault)
#       -> auto-RECOVER the instance (same IP, same disk) + email
#   - Alarm 2: INSTANCE status check fail (OS wedge, OOM-thrash — what
#       happened on 2026-06-10) -> auto-REBOOT + email
#   - Alarm 3: CPU credit balance low (t3.micro burst exhaustion) -> email
set -euo pipefail

INSTANCE_ID=i-047f1ad7256084171
REGION=us-east-1
EMAIL=matthewthelim@gmail.com

TOPIC_ARN=$(aws sns create-topic --name polymarket-ec2-alerts \
  --region "$REGION" --query TopicArn --output text)
aws sns subscribe --topic-arn "$TOPIC_ARN" --protocol email \
  --notification-endpoint "$EMAIL" --region "$REGION"
echo "SNS topic: $TOPIC_ARN  (check your inbox and CONFIRM the subscription)"

# Alarm 1 — hardware/system failure: auto-recover (keeps IP and disk)
aws cloudwatch put-metric-alarm --region "$REGION" \
  --alarm-name polymarket-ec2-system-check \
  --alarm-description "Collector box: AWS-side failure -> auto-recover + email" \
  --namespace AWS/EC2 --metric-name StatusCheckFailed_System \
  --dimensions Name=InstanceId,Value="$INSTANCE_ID" \
  --statistic Maximum --period 60 --evaluation-periods 2 \
  --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions "arn:aws:automate:$REGION:ec2:recover" "$TOPIC_ARN"

# Alarm 2 — OS-level failure (the 2026-06-10 OOM wedge): auto-reboot
aws cloudwatch put-metric-alarm --region "$REGION" \
  --alarm-name polymarket-ec2-instance-check \
  --alarm-description "Collector box: OS wedged -> auto-reboot + email" \
  --namespace AWS/EC2 --metric-name StatusCheckFailed_Instance \
  --dimensions Name=InstanceId,Value="$INSTANCE_ID" \
  --statistic Maximum --period 60 --evaluation-periods 3 \
  --threshold 1 --comparison-operator GreaterThanOrEqualToThreshold \
  --alarm-actions "arn:aws:automate:$REGION:ec2:reboot" "$TOPIC_ARN"

# Alarm 3 — burst-credit exhaustion warning (t3.micro under 26 WS connections)
aws cloudwatch put-metric-alarm --region "$REGION" \
  --alarm-name polymarket-ec2-cpu-credits-low \
  --alarm-description "Collector box: CPU credits below 20 -> email (consider t3.small)" \
  --namespace AWS/EC2 --metric-name CPUCreditBalance \
  --dimensions Name=InstanceId,Value="$INSTANCE_ID" \
  --statistic Average --period 300 --evaluation-periods 2 \
  --threshold 20 --comparison-operator LessThanOrEqualToThreshold \
  --alarm-actions "$TOPIC_ARN"

echo "Done. Alarms:"
aws cloudwatch describe-alarms --region "$REGION" \
  --alarm-name-prefix polymarket-ec2 \
  --query "MetricAlarms[].{Name:AlarmName,State:StateValue}" --output table

# ---------------------------------------------------------------------------
# OPTIONAL (recommended, run separately): Elastic IP so the address survives
# stop/start. WARNING: associating it CHANGES the current public IP — update
# EC2_HOST in run_live_backtest.py / run_sensitivity.py and Ec2Host in
# scripts/ec2_watchdog.ps1 afterwards.
#
# ALLOC=$(aws ec2 allocate-address --region $REGION --query AllocationId --output text)
# aws ec2 associate-address --region $REGION --instance-id $INSTANCE_ID --allocation-id $ALLOC
# aws ec2 describe-addresses --region $REGION --allocation-ids $ALLOC \
#   --query "Addresses[0].PublicIp" --output text
#
# OPTIONAL: upgrade to t3.small (fixes the 1GB OOM root cause, ~$8/mo more).
# WARNING: stop/start changes the public IP unless the Elastic IP above is
# attached first. ~3 minutes of collection downtime.
#
# aws ec2 stop-instances --region $REGION --instance-ids $INSTANCE_ID
# aws ec2 wait instance-stopped --region $REGION --instance-ids $INSTANCE_ID
# aws ec2 modify-instance-attribute --region $REGION --instance-id $INSTANCE_ID \
#   --instance-type t3.small
# aws ec2 start-instances --region $REGION --instance-ids $INSTANCE_ID
# ---------------------------------------------------------------------------
