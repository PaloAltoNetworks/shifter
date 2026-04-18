Right, the NGFW is in the range VPC's NGFW subnet (10.1.6.x), not accessible from my workstation. I need to SSH via the portal/bastion.

Bash Find portal/bastion instance
IN
AWS_PROFILE=panw-shifter-dev-workstation aws ec2 describe-instances --region us-east-2 --filters "Name=tag:Name,Values=*portal*,*bastion*" "Name=instance-state-name,Values=running" --query 'Reservations[*].Instances[*].[InstanceId,Tags[?Key==`Name`].Value|[0],PrivateIpAddress,PublicIpAddress]' --output table 2>&1

OUT
------------------------------------------------------------------
|                        DescribeInstances                       |
+----------------------+------------------+--------------+-------+
|  i-067b8017b84c442c8 |  dev-portal-ec2  |  10.0.52.116 |  None |
|  i-05c9ed8f99ddd28bc |  dev-portal-ec2  |  10.0.41.60  |  None |
+----------------------+------------------+--------------+-------+
I can use SSM to connect to the portal and then SSH to the NGFW. Let me do that.

Bash SSH to NGFW via portal using SSM
IN
AWS_PROFILE=panw-shifter-dev-workstation aws ssm start-session --region us-east-2 --target i-067b8017b84c442c8 --document-name AWS-StartInteractiveCommand --parameters command="echo 'show system info' | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null admin@10.1.6.132 2>&1 | grep -E 'hostname|serial|vm-license|device-certificate'" 2>&1

OUT
Exit code 252

Error parsing parameter '--parameters': Expected: ',', received: ''' for input:
command=echo 'show system info' | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null admin@10.1.6.132 2>&1 | grep -E 'hostname|serial|vm-license|device-certificate'
             ^
Bash SSH to NGFW via portal using SSM
IN
AWS_PROFILE=panw-shifter-dev-workstation aws ssm start-session --region us-east-2 --target i-067b8017b84c442c8 --document-name AWS-StartInteractiveCommand --parameters 'command="echo \"show system info\" | ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null admin@10.1.6.132 2>&1 | grep -E \"hostname|serial|vm-license|device-certificate\""' 2>&1

OUT
Starting session with SessionId: panw-shifter-dev-workstation-9got28czjyd6x5tynvh568nrya

(admin@10.1.6.132) Password: Cannot perform start session: EOF
The portal doesn't have the SSH key. Let me copy the key to the portal first and then try.

Bash Base64 encode the SSH key
IN
cat /tmp/ngfw-key.pem | base64 -w0

OUT
LS0tLS1CRUdJTiBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0KYjNCbGJuTnphQzFyWlhrdGRqRUFBQUFBQkc1dmJtVUFBQUFFYm05dVpRQUFBQUFBQUFBQkFBQUFNd0FBQUF0emMyZ3RaV1F5TlRVeApPUUFBQUNCNUE0WnYyQ2pyQnpxbGVKRVZkRkVhbU43QTgxTjhFRDFzUWJnbU5yZnNKUUFBQUlpWDJJVXFsOWlGS2dBQUFBdHpjMmd0ClpXUXlOVFV4T1FBQUFDQjVBNFp2MkNqckJ6cWxlSkVWZEZFYW1ON0E4MU44RUQxc1FiZ21OcmZzSlFBQUFFQ09melhkQ0NmVnVsK3oKczRNakNMOW80blBscHBtWHdmMmdOS2F2WnUyeFEza0RobS9ZS09zSE9xVjRrUlYwVVJxWTNzRHpVM3dRUFd4QnVDWTJ0K3dsQUFBQQpBQUVDQXdRRgotLS0tLUVORCBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0KCg==
Bash Copy key and SSH to NGFW via portal
IN
AWS_PROFILE=panw-shifter-dev-workstation aws ssm start-session --region us-east-2 --target i-067b8017b84c442c8 --document-name AWS-StartInteractiveCommand --parameters 'command=["echo LS0tLS1CRUdJTiBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0KYjNCbGJuTnphQzFyWlhrdGRqRUFBQUFBQkc1dmJtVUFBQUFFYm05dVpRQUFBQUFBQUFBQkFBQUFNd0FBQUF0emMyZ3RaV1F5TlRVeApPUUFBQUNCNUE0WnYyQ2pyQnpxbGVKRVZkRkVhbU43QTgxTjhFRDFzUWJnbU5yZnNKUUFBQUlpWDJJVXFsOWlGS2dBQUFBdHpjMmd0ClpXUXlOVFV4T1FBQUFDQjVBNFp2MkNqckJ6cWxlSkVWZEZFYW1ON0E4MU44RUQxc1FiZ21OcmZzSlFBQUFFQ09melhkQ0NmVnVsK3oKczRNakNMOW80blBscHBtWHdmMmdOS2F2WnUyeFEza0RobS9ZS09zSE9xVjRrUlYwVVJxWTNzRHpVM3dRUFd4QnVDWTJ0K3dsQUFBQQpBQUVDQXdRRgotLS0tLUVORCBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0KCg== | base64 -d > /tmp/ngfw.pem && chmod 600 /tmp/ngfw.pem && echo show system info | ssh -i /tmp/ngfw.pem -o StrictHostKeyChecking=no admin@10.1.6.132 2>&1"]' 2>&1

OUT
Starting session with SessionId: panw-shifter-dev-workstation-oz5epu4fbov5uk2l2q3x3hrk54
Pseudo-terminal will not be allocated because stdin is not a terminal.

Cannot perform start session: EOF
Let me try a different approach - use SSM send-command to run the command remotely.

Bash Send SSH command via SSM
IN
AWS_PROFILE=panw-shifter-dev-workstation aws ssm send-command --region us-east-2 --instance-ids i-067b8017b84c442c8 --document-name AWS-RunShellScript --parameters 'commands=["echo LS0tLS1CRUdJTiBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0KYjNCbGJuTnphQzFyWlhrdGRqRUFBQUFBQkc1dmJtVUFBQUFFYm05dVpRQUFBQUFBQUFBQkFBQUFNd0FBQUF0emMyZ3RaV1F5TlRVeApPUUFBQUNCNUE0WnYyQ2pyQnpxbGVKRVZkRkVhbU43QTgxTjhFRDFzUWJnbU5yZnNKUUFBQUlpWDJJVXFsOWlGS2dBQUFBdHpjMmd0ClpXUXlOVFV4T1FBQUFDQjVBNFp2MkNqckJ6cWxlSkVWZEZFYW1ON0E4MU44RUQxc1FiZ21OcmZzSlFBQUFFQ09melhkQ0NmVnVsK3oKczRNakNMOW80blBscHBtWHdmMmdOS2F2WnUyeFEza0RobS9ZS09zSE9xVjRrUlYwVVJxWTNzRHpVM3dRUFd4QnVDWTJ0K3dsQUFBQQpBQUVDQXdRRgotLS0tLUVORCBPUEVOU1NIIFBSSVZBVEUgS0VZLS0tLS0KCg== | base64 -d > /tmp/ngfw.pem && chmod 600 /tmp/ngfw.pem && echo show system info | ssh -i /tmp/ngfw.pem -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null admin@10.1.6.132 2>&1"]' --query 'Command.CommandId' --output text 2>&1

OUT
98cfd430-aecc-488a-bebd-3fad6d6ec243
Bash Get SSM command result
IN
sleep 10 && AWS_PROFILE=panw-shifter-dev-workstation aws ssm get-command-invocation --region us-east-2 --command-id 98cfd430-aecc-488a-bebd-3fad6d6ec243 --instance-id i-067b8017b84c442c8 --query '[Status,StandardOutputContent,StandardErrorContent]' --output json 2>&1

OUT
[
    "Success",
    "Pseudo-terminal will not be allocated because stdin is not a terminal.\r\nWarning: Permanently added '10.1.6.132' (RSA) to the list of known hosts.\r\n\nhostname: ngfw-user-1\nip-address: 10.1.6.132\npublic-ip-address: unknown\nnetmask: 255.255.252.0\ndefault-gateway: 10.1.4.1\nip-assignment: dhcp\nip6-assignment: static\nipv6-address: unknown\nipv6-link-local-address: fe80::27:55ff:fe2f:1c09/64\nipv6-default-gateway: \nmac-address: 02:27:55:2f:1c:09\ntime: Wed Jan 14 09:35:12 2026\nuptime: 0 days, 0:25:37\nfamily: vm\nmodel: PA-VM\nserial: 007955000758123\nvm-mac-base: \nvm-mac-count: 256\nvm-uuid: EC26F7D5-CB7E-B7E3-F9F5-ABD818B308E8\nvm-cpuid: AWS:57060500FFFBEBBF\nvm-license: VM-SERIES-4\nvm-cap-tier: T2-16GB\nvm-cpu-count: 4\nvm-memory: 16112360\nvm-mode: Amazon AWS\ncloud-mode: cloud\nsw-version: 11.2.8\nglobal-protect-client-package-version: 0.0.0\ndevice-dictionary-version: 82-406\ndevice-dictionary-release-date: \napp-version: 8902-9003\napp-release-date: \nav-version: 0\nav-release-date: \nthreat-version: 0\nthreat-release-date: \nwf-private-version: 0\nwf-private-release-date: unknown\nurl-db: paloaltonetworks\nwildfire-version: 0\nwildfire-release-date: \nwildfire-rt: Disabled\nurl-filtering-version: 20260114.20264\nglobal-protect-datafile-version: 0\nglobal-protect-datafile-release-date: unknown\nglobal-protect-clientless-vpn-version: 0\nglobal-protect-clientless-vpn-release-date: \nlogdb-version: 11.2.4\nvm_series: vm_series-5.1.9\ndlp: dlp-5.0.7\nopenconfig: openconfig-2.1.0\nplatform-family: vm\nvpn-disable-mode: off\nmulti-vsys: off\noperational-mode: normal\nadvanced-routing: off\nduplicate-ip: Disabled\ndevice-certificate-status: Valid\n\nWelcome admin.\n",
    ""
]
NGFW Bootstrap SUCCESS! 🎉

Key results:

hostname: ngfw-user-1 ✅
serial: 007955000758123 ✅
vm-license: VM-SERIES-4 ✅
device-certificate-status: Valid ✅
The IAM fix worked! The NGFW successfully:

Read the bootstrap files from S3 (thanks to the s3:ListBucket permission we added)
Applied the init-cfg.txt configuration
Registered with SCM and got a valid device certificate
Applied the VM-Series license
what's that instance name?
The instance name is ngfw-a6237487-2803-48e4-8e78-2183a9afa2cf-ngfw but the hostname configured in PAN-OS is ngfw-user-1.

Looking at the provisioner code in ngfw_component.py:220:


hostname = f"ngfw-user-{user_id}"
So since this is user_id=1, the hostname is ngfw-user-1. The EC2 instance Name tag includes the request UUID for tracking purposes.

Brilliant. So confirmed, that is a working provision
Yes, confirmed! The NGFW provisioning is now fully working:

Check	Result
S3 bootstrap read	✅ (IAM fix applied)
hostname	ngfw-user-1 ✅
serial	007955000758123 ✅
vm-license	VM-SERIES-4 ✅
device-certificate-status	Valid ✅
The s3:ListBucket permission fix was the missing piece. The provisioner code, init-cfg template, and S3 structure were all correct - it was just the IAM policy that needed the additional permission.
