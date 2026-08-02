# Docker DNS and Brevo SMTP recovery

Status: **production verification required**. The repository workspace is not the
Ubuntu EC2 deployment host and has no production environment file or AWS Compose
override. Do not apply a DNS override until the host evidence below identifies the
failed forwarding path.

## Current incident evidence

- The EC2 host resolves `smtp-relay.brevo.com`.
- The backend and training-worker containers use Docker's embedded resolver at
  `127.0.0.11` and do not resolve the Brevo hostname.
- A direct SMTP probe fails with `gaierror` before a TCP connection is opened.
- Brevo has no corresponding transactional event.

`127.0.0.11` inside a user-defined Docker network is expected. It does not prove
that service-level `dns:` values were ignored: Docker keeps the embedded address
inside the container and forwards queries to the selected upstream resolvers. The
evidence currently narrows the incident to Docker DNS forwarding, its upstream
resolver selection, or UDP/TCP 53 forwarding/NAT. It does not yet distinguish
among them.

## Read-only diagnostic sequence

Run on the EC2 host. Do not print `.env.production` or inspect container
environment values.

```bash
docker version
sudo test -f /etc/docker/daemon.json && sudo cat /etc/docker/daemon.json || echo "daemon.json does not exist"
cat /etc/resolv.conf
resolvectl status
getent hosts smtp-relay.brevo.com
getent hosts google.com
docker network ls
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Networks}}'
docker inspect ai-manufacturing-platform-backend-1 --format '{{json .HostConfig.Dns}} {{json .HostConfig.DnsOptions}} {{json .HostConfig.DnsSearch}} {{.HostConfig.NetworkMode}} {{.ResolvConfPath}}'
docker inspect ai-manufacturing-platform-training-worker-1 --format '{{json .HostConfig.Dns}} {{json .HostConfig.DnsOptions}} {{json .HostConfig.DnsSearch}} {{.HostConfig.NetworkMode}} {{.ResolvConfPath}}'
docker exec ai-manufacturing-platform-backend-1 getent hosts smtp-relay.brevo.com
docker exec ai-manufacturing-platform-training-worker-1 getent hosts smtp-relay.brevo.com
sudo iptables -S
sudo iptables -t nat -S
sudo nft list ruleset
sudo ufw status verbose
sudo journalctl -u docker --since '2 hours ago'
sudo journalctl -u systemd-resolved --since '2 hours ago'
```

Render the effective deployment configuration without redirecting it to a tracked
file. Review only configuration keys; never paste secret-expanded output into a
ticket or commit it.

```bash
docker compose -p ai-manufacturing-platform --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml \
  -f docker-compose.https.yml -f docker-compose.aws.yml config
```

Inspect `docker-compose.dns.yml` separately if present. Attach a disposable image
to the exact production application network and compare default, VPC, and public
resolver queries over both UDP and TCP 53. Record the network name explicitly
before running the probe; do not guess it.

## Fix decision

Choose the smallest result supported by the diagnostics:

1. Repair host/systemd-resolved upstream selection if the host-side stub or VPC
   resolver fails direct queries.
2. Repair firewall/NAT forwarding if direct host queries pass but queries sourced
   from the Docker bridge cannot reach UDP or TCP 53.
3. Configure validated upstream resolvers in Docker's daemon configuration only
   when bridge forwarding works and daemon upstream selection is the failure.
4. Use a tracked service-level Compose DNS override only when a disposable
   container on the same production network proves that exact resolver works.

Never hardcode a Brevo IP, edit a running container's `/etc/resolv.conf`, use host
networking, or disable firewall policy broadly.

## Controlled change and rollback

Before a daemon change, record `docker ps`, confirm restart policies, and create a
root-owned timestamped backup of `/etc/docker/daemon.json`. Validate edited JSON
before restarting Docker. A Docker restart affects running containers; do not run
`docker compose down` and do not remove volumes.

For a tracked Compose-only change, rollback with the reviewed reverse patch, then
recreate only the affected services:

```bash
docker compose -p ai-manufacturing-platform --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml \
  -f docker-compose.https.yml -f docker-compose.aws.yml \
  up -d --no-deps --force-recreate backend training-worker
```

For a daemon change, restore the recorded backup, validate the JSON, perform one
controlled Docker restart, and verify every previous container recovers. Re-run
host, backend, worker, and disposable-container DNS checks after rollback.

## SMTP and application acceptance

After DNS succeeds, use a credential-redacted probe from the training worker that
reports only DNS, TCP, STARTTLS, and authentication success/failure. It must read
credentials internally without printing them. Trigger exactly one reset request
for a dedicated acceptance account, then verify the durable message reaches
`sent`, the worker records one successful outcome, Brevo records the event, and
the inbox or spam folder receives it.

Acceptance also requires all containers healthy and
`https://factorymind.ddnsgeek.com` returning HTTP 200. Until those checks are run
on EC2, production DNS and Brevo delivery remain unaccepted.
