---
name: deploy-external-tools
description: Deploys the latest master of automation-tools to the production external-tools EC2 host. Use when shipping changes to main.py, src/python/, static/, or templates/ that should run on the external-tools service.
---

# Deploy to external-tools

The external-tools host runs the FastAPI app from `main.py` as a systemd service in Stream Security's production AWS account. This skill walks through a 5-minute deploy: pull the new code, restart the service, verify it's healthy, with a rollback path if needed.

## Prerequisites

1. **AWS production credentials** (SSO or env vars) with EC2 read for instance lookup. If you also need to modify the SG to add your IP, you need EC2 write on the host's security group.
2. **The `external-tools.pem` SSH key.** This host uses a dedicated keypair, NOT the standard prod key. Ask a teammate or pull from your team's secret store; don't generate a new one.
3. **Network access on port 22.** The host's SG is restrictive — port 22 is allowed only from a small set of known IPs:
   - Stream office NAT — works automatically if you're at the office.
   - Otherwise, add your current public IP to the SG temporarily (see "Adding your IP" below) and revoke when done.

## 1. Find the host

```bash
aws --profile <prod-profile> ec2 describe-instances \
  --filters "Name=tag:Name,Values=external-tools" "Name=instance-state-name,Values=running" \
  --query 'Reservations[].Instances[].{Id:InstanceId,PubIP:PublicIpAddress,PrivIP:PrivateIpAddress,SG:SecurityGroups[].GroupId}' \
  --output table
```

Use the **PubIP** for SSH (the host is in an isolated VPC that's not routable from other prod VPCs).

## 2. Deploy

```bash
HOST=<public-ip-from-step-1>
KEY=/path/to/external-tools.pem  # adjust to where you keep it

ssh -i "$KEY" ec2-user@"$HOST" 'bash -s' << 'EOF'
set -e
cd /home/ec2-user/automation-tools

# Snapshot for rollback
git rev-parse HEAD | sudo tee /tmp/pre-deploy-sha.txt

# Pull (fast-forward only — refuses on diverged history)
sudo git fetch origin
sudo git pull --ff-only origin master
git log -1 --oneline

# Restart
sudo systemctl restart external_tools_app.service
sleep 3
sudo systemctl status external_tools_app.service --no-pager | head -10

# Verify
sudo ss -ltnp | grep ':80\b'
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' http://localhost/
sudo journalctl -u external_tools_app.service --since '1 min ago' --no-pager | tail -10
EOF
```

Expected output:
- `Active: active (running)` from systemctl
- `HTTP 200` from the curl
- No tracebacks/errors in the journalctl tail
- A few `GET / HTTP/1.1 200 OK` lines from internal clients within seconds of restart

## 3. Rollback (if verification fails)

```bash
ssh -i "$KEY" ec2-user@"$HOST" '
cd /home/ec2-user/automation-tools
sudo git checkout $(cat /tmp/pre-deploy-sha.txt)
sudo systemctl restart external_tools_app.service
'
```

Then re-run the verification commands.

## Adding your IP to the SG (when not at the office)

```bash
MY_IP=$(curl -sS https://api.ipify.org)
SG_ID=<sg-id-from-step-1>
RULE_ID=$(aws --profile <prod-profile> ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${MY_IP}/32,Description=\"Temp deploy access $(whoami) $(date +%F)\"}]" \
  --query 'SecurityGroupRules[0].SecurityGroupRuleId' --output text)
echo "Rule ID: $RULE_ID — keep this for revoke"
```

After deploying, revoke:
```bash
aws --profile <prod-profile> ec2 revoke-security-group-ingress \
  --group-id "$SG_ID" --security-group-rule-ids "$RULE_ID"
```

## Notes

- The service runs as **root** because it binds directly to port 80 (no nginx fronting). The systemd unit lives at `/etc/systemd/system/external_tools_app.service`.
- The repo at `/home/ec2-user/automation-tools` has its `.git/` directory owned by root — always use `sudo git ...`.
- **No venv.** Uses system `python3` with system-installed dependencies. `pip install -r requirements.txt` is normally a no-op; only run it if you've added a real new dependency, and skip otherwise to avoid surprises.
- **Lambda code under `lambda/` does NOT deploy here** — those files run as separate AWS Lambda functions and need their own deploy path (`lambda/organization_integration/org_lambda.py`).
- This host is set up off-pattern relative to other prod hosts (its own keypair, single-instance VPC, manually configured SG, no IaC). If it's ever rebuilt, get it into Terraform alongside the rest of prod — that would also fix the deploy access mess this skill exists to work around.
