#!/usr/bin/env python3
"""Launch / manage an EC2 instance to run the llm-feedback-control experiments
with a LARGE local Ollama "ceiling" model (e.g. mixtral:8x7b, ~26 GB) that is
impractical on a laptop.

Right-sized for the scenario:
  * a big-RAM CPU instance (mixtral q4 ~26 GB needs ~64 GB RAM; a single
    affordable GPU can't hold it, so CPU big-RAM is the optimal-not-overkill
    choice — slower per call, but cheap);
  * the model is cached to S3 so terminating the instance doesn't lose it
    (~$0.64/month for 28 GB);
  * the small model (phi3:mini) runs here too, but it also runs fine on a
    laptop — the only reason for EC2 is the big ceiling model.

A minimal, self-contained EC2 provisioning harness (Ollama + an S3 model cache).

Usage:
  pip install boto3
  python aws/launch.py --upload-code      # tar this project -> S3
  python aws/launch.py                     # provision r6i.2xlarge + bootstrap
  python aws/ssm.py "tail -30 /var/log/llm-fbc-setup.log"
  python aws/ssm.py --timeout 1800 "bash /home/ubuntu/setup.sh"   # pull/restore models + fetch code
  python aws/launch.py --stop | --start | --terminate | --status
"""
import argparse, boto3, json, time, tarfile, io, os
from datetime import datetime
from pathlib import Path

REGION = 'us-east-1'
TAG_PROJECT = 'llm-fbc'
TAG_KEY = 'Project'
KEY_PAIR_NAME = 'llm-fbc-key'
SECURITY_GROUP_NAME = 'llm-fbc-sg'
IAM_PROFILE_NAME = 'llm-fbc-profile'
IAM_ROLE_NAME = 'llm-fbc-role'
INSTANCE_ID_FILE = Path(__file__).parent / '.instance_id'
PROJECT_DIR = Path(__file__).parent.parent          # the llm-feedback-control root

DEFAULT_INSTANCE_TYPE = 'r6i.2xlarge'               # 8 vCPU, 64 GB RAM (~$0.50/hr)
EBS_GB = 80                                         # Ubuntu + Ollama + mixtral 26GB + phi3 + headroom

# S3: durable cache for the Ollama models + a tarball of this code.
BUCKET = f'llm-fbc-{boto3.client("sts").get_caller_identity()["Account"]}'
MODELS_KEY = 'ollama-models.tar'                    # tar of /usr/share/ollama/.ollama/models
CODE_KEY = 'code/llm-feedback-control.tar.gz'
SMALL_MODEL = 'phi3:mini'
CEILING_MODEL = 'mixtral:8x7b-instruct-v0.1-q4_K_M'


def log(m): print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)
def save_id(i): INSTANCE_ID_FILE.write_text(i)
def load_id(): return INSTANCE_ID_FILE.read_text().strip() if INSTANCE_ID_FILE.exists() else None


def ensure_bucket(s3):
    """Create the S3 model/code cache bucket if it doesn't already exist."""
    try:
        s3.head_bucket(Bucket=BUCKET); log(f"  S3 bucket exists: {BUCKET}")
    except Exception:
        log(f"Creating S3 bucket: {BUCKET}")
        s3.create_bucket(Bucket=BUCKET)   # us-east-1: no LocationConstraint


def upload_code(args):
    """Tar src/ + experiments/ (and key root files) and upload to S3 for the instance to fetch."""
    s3 = boto3.client('s3', region_name=REGION); ensure_bucket(s3)
    buf = io.BytesIO()
    skip = lambda ti: None if '__pycache__' in ti.name or ti.name.endswith('.pyc') else ti
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        # package source + the repro experiments, preserving the directory layout
        for d in ('src', 'experiments'):
            dp = PROJECT_DIR / d
            if dp.exists(): tar.add(dp, arcname=d, filter=skip)
        for extra in ('pyproject.toml', 'README.md', 'LICENSE'):
            fp = PROJECT_DIR / extra
            if fp.exists(): tar.add(fp, arcname=extra)
    buf.seek(0)
    s3.put_object(Bucket=BUCKET, Key=CODE_KEY, Body=buf.getvalue())
    log(f"  Uploaded code -> s3://{BUCKET}/{CODE_KEY} ({len(buf.getvalue())//1024} KB)")


def get_ubuntu_ami(ec2):
    """Return the AMI ID of the newest Canonical Ubuntu 22.04 (jammy) x86_64 image."""
    r = ec2.describe_images(
        Filters=[{'Name': 'name', 'Values': ['ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*']},
                 {'Name': 'state', 'Values': ['available']},
                 {'Name': 'architecture', 'Values': ['x86_64']}],
        Owners=['099720109477'])
    return sorted(r['Images'], key=lambda x: x['CreationDate'], reverse=True)[0]['ImageId']


def ensure_key_pair(ec2):
    """Reuse or create the EC2 key pair, saving any new private key to ~/.ssh; returns its name."""
    kf = Path.home() / '.ssh' / f'{KEY_PAIR_NAME}.pem'
    try:
        ec2.describe_key_pairs(KeyNames=[KEY_PAIR_NAME]); log(f"  Key pair exists: {KEY_PAIR_NAME}"); return KEY_PAIR_NAME
    except ec2.exceptions.ClientError:
        pass
    r = ec2.create_key_pair(KeyName=KEY_PAIR_NAME); kf.parent.mkdir(parents=True, exist_ok=True)
    kf.write_text(r['KeyMaterial']); kf.chmod(0o600); log(f"  Key saved: {kf}"); return KEY_PAIR_NAME


def ensure_sg(ec2):
    """Reuse or create the security group (SSH/22 open) and return its GroupId."""
    r = ec2.describe_security_groups(Filters=[{'Name': 'group-name', 'Values': [SECURITY_GROUP_NAME]}])
    if r['SecurityGroups']:
        return r['SecurityGroups'][0]['GroupId']
    sg = ec2.create_security_group(GroupName=SECURITY_GROUP_NAME, Description='llm-fbc dev')['GroupId']
    ec2.authorize_security_group_ingress(GroupId=sg, IpPermissions=[
        {'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}])
    log(f"  Created SG: {sg}"); return sg


def ensure_iam(iam):
    """Reuse or create the IAM role + instance profile (SSM + S3 access); returns profile name."""
    try:
        iam.get_instance_profile(InstanceProfileName=IAM_PROFILE_NAME); log(f"  IAM profile exists"); return IAM_PROFILE_NAME
    except iam.exceptions.NoSuchEntityException:
        pass
    trust = {"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
             "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    try: iam.create_role(RoleName=IAM_ROLE_NAME, AssumeRolePolicyDocument=json.dumps(trust))
    except iam.exceptions.EntityAlreadyExistsException: pass
    for arn in ['arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore',
                'arn:aws:iam::aws:policy/AmazonS3FullAccess']:
        try: iam.attach_role_policy(RoleName=IAM_ROLE_NAME, PolicyArn=arn)
        except Exception: pass
    try: iam.create_instance_profile(InstanceProfileName=IAM_PROFILE_NAME)
    except iam.exceptions.EntityAlreadyExistsException: pass
    try: iam.add_role_to_instance_profile(InstanceProfileName=IAM_PROFILE_NAME, RoleName=IAM_ROLE_NAME)
    except Exception: pass
    log("  Waiting for IAM propagation..."); time.sleep(12); return IAM_PROFILE_NAME


def user_data():
    """Return the cloud-init bootstrap script: install Ollama + write the phase-2 setup.sh."""
    return f'''#!/bin/bash
set -e
exec > >(tee /var/log/llm-fbc-setup.log) 2>&1
echo "=== llm-fbc bootstrap: $(date) ==="
export HOME=/home/ubuntu; cd /home/ubuntu
sleep 10
apt-get update -qq
apt-get install -y -qq python3-pip awscli curl tmux
echo "Installing Ollama..."
curl -fsSL https://ollama.com/install.sh | sh
systemctl enable ollama; systemctl start ollama
sleep 5

# Phase-2 script: restore models from S3 if cached, else pull + cache; fetch code.
cat > /home/ubuntu/setup.sh << 'P2'
#!/bin/bash
set -e
export HOME=/home/ubuntu; cd /home/ubuntu
BUCKET={BUCKET}
MODELS_DIR=/usr/share/ollama/.ollama/models
if aws s3 ls s3://$BUCKET/{MODELS_KEY} >/dev/null 2>&1; then
    echo "Restoring Ollama models from S3 cache..."
    aws s3 cp s3://$BUCKET/{MODELS_KEY} /tmp/models.tar
    sudo systemctl stop ollama
    sudo tar -xf /tmp/models.tar -C /
    sudo systemctl start ollama; sleep 5
else
    echo "No S3 cache; pulling models from Ollama registry..."
    ollama pull {SMALL_MODEL}
    ollama pull {CEILING_MODEL}
    echo "Caching models to S3 (so we don't re-download after terminate)..."
    sudo tar -cf /tmp/models.tar $MODELS_DIR
    aws s3 cp /tmp/models.tar s3://$BUCKET/{MODELS_KEY}
fi
echo "Fetching code from S3..."
aws s3 cp s3://$BUCKET/{CODE_KEY} /tmp/code.tar.gz
mkdir -p /home/ubuntu/llm-feedback-control
tar -xzf /tmp/code.tar.gz -C /home/ubuntu/llm-feedback-control
echo "Installing the package (zero deps)..."
pip3 install -q /home/ubuntu/llm-feedback-control
echo "Models available:"; ollama list
echo "Run an experiment, e.g.:  python3 /home/ubuntu/llm-feedback-control/experiments/hard_corpus.py"
echo "=== setup complete ==="
P2
chmod +x /home/ubuntu/setup.sh; chown ubuntu:ubuntu /home/ubuntu/setup.sh
echo "=== Phase 1 bootstrap complete ==="
'''


def find_instance(ec2):
    """Return the first non-terminated instance tagged for this project, or None."""
    r = ec2.describe_instances(Filters=[
        {'Name': f'tag:{TAG_KEY}', 'Values': [TAG_PROJECT]},
        {'Name': 'instance-state-name', 'Values': ['pending', 'running', 'stopping', 'stopped']}])
    for res in r['Reservations']:
        for inst in res['Instances']:
            return inst
    return None


def show(inst):
    ip = inst.get('PublicIpAddress', '<pending>')
    log(f"Instance {inst['InstanceId']} ({inst['State']['Name']}) {inst['InstanceType']} ip={ip}")


def launch(args):
    """Provision the EC2 instance (reusing any existing one): bucket, AMI, key, SG, IAM, run + wait."""
    ec2 = boto3.client('ec2', region_name=REGION); iam = boto3.client('iam', region_name=REGION)
    s3 = boto3.client('s3', region_name=REGION)
    existing = find_instance(ec2)
    if existing:
        log(f"Existing instance: {existing['InstanceId']} ({existing['State']['Name']})"); show(existing); return
    ensure_bucket(s3)
    log(f"Launching {args.instance_type} ({'spot' if args.spot else 'on-demand'})")
    ami = get_ubuntu_ami(ec2); key = ensure_key_pair(ec2); sg = ensure_sg(ec2); prof = ensure_iam(iam)
    kw = dict(ImageId=ami, InstanceType=args.instance_type, MinCount=1, MaxCount=1, KeyName=key,
              UserData=user_data(), IamInstanceProfile={'Name': prof}, SecurityGroupIds=[sg],
              BlockDeviceMappings=[{'DeviceName': '/dev/sda1',
                  'Ebs': {'VolumeSize': EBS_GB, 'VolumeType': 'gp3', 'DeleteOnTermination': True}}],
              TagSpecifications=[{'ResourceType': 'instance',
                  'Tags': [{'Key': 'Name', 'Value': 'llm-fbc'}, {'Key': TAG_KEY, 'Value': TAG_PROJECT}]}])
    if args.spot:
        kw['InstanceMarketOptions'] = {'MarketType': 'spot'}
    r = ec2.run_instances(**kw); iid = r['Instances'][0]['InstanceId']; save_id(iid)
    log(f"Launched {iid}; waiting for running...")
    ec2.get_waiter('instance_running').wait(InstanceIds=[iid])
    show(ec2.describe_instances(InstanceIds=[iid])['Reservations'][0]['Instances'][0])
    log("Bootstrapping (~3-4 min: apt + Ollama). Then:")
    log("  python aws/ssm.py \"tail -30 /var/log/llm-fbc-setup.log\"")
    log("  python aws/ssm.py --timeout 1800 \"bash /home/ubuntu/setup.sh\"   # pull/restore + fetch code")


def _simple(action):
    ec2 = boto3.client('ec2', region_name=REGION); inst = find_instance(ec2)
    if not inst: log("No instance found."); return
    iid = inst['InstanceId']
    if action == 'status': show(inst)
    elif action == 'stop': ec2.stop_instances(InstanceIds=[iid]); log(f"Stopping {iid}")
    elif action == 'start': ec2.start_instances(InstanceIds=[iid]); log(f"Starting {iid}")
    elif action == 'terminate':
        ec2.terminate_instances(InstanceIds=[iid]); log(f"Terminating {iid} (model persists on S3)")
        INSTANCE_ID_FILE.unlink(missing_ok=True)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--instance-type', default=DEFAULT_INSTANCE_TYPE)
    ap.add_argument('--spot', action='store_true')
    for a in ('upload-code', 'status', 'stop', 'start', 'terminate'):
        ap.add_argument(f'--{a}', action='store_true')
    args = ap.parse_args()
    if args.upload_code: upload_code(args)
    elif args.status: _simple('status')
    elif args.stop: _simple('stop')
    elif args.start: _simple('start')
    elif args.terminate: _simple('terminate')
    else: launch(args)
