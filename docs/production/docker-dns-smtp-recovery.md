# Docker DNS and Brevo SMTP recovery

Status: **root cause confirmed on the production EC2 host**. The tracked recovery
is a dedicated egress-capable network for the backend and training worker. It does
not publish a port or weaken the internal application, data, or observability
networks.

## Current incident evidence

- The EC2 host resolves `smtp-relay.brevo.com`.
- The backend and training-worker containers use Docker's embedded resolver at
  `127.0.0.11` and do not resolve the Brevo hostname.
- A direct SMTP probe failed with `gaierror` before a TCP connection was opened.
- Direct connections from both application containers to the VPC resolver failed
  with `Network is unreachable`.
- Docker's journal showed the same routing failure for public, EC2, and VPC DNS
  upstreams. UFW was inactive and the host output policy was `ACCEPT`.
- Both services were attached only to `internal: true` networks, which have no
  external gateway. A disposable container on the same application network
  reproduced the failure; the same image on a disposable routable bridge resolved
  Brevo and connected to TCP/587 successfully.

`127.0.0.11` inside a user-defined Docker network is expected. Docker keeps that
embedded address and forwards queries to upstream resolvers. In this incident,
changing the upstream address cannot help because the containers have no route to
any upstream. Do not add daemon-level or service-level DNS overrides for this
failure mode.

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

The confirmed fix is to retain all existing internal networks and add the normal
Compose `egress` bridge only to `backend` and `training-worker`. A routable bridge
permits outbound DNS/HTTPS/SMTP but does not publish a service port. Static tests
enforce that no other production service joins this network and neither outbound
service publishes a port.

The decision order remains useful for future incidents: repair host resolution
first, then firewall/NAT forwarding, then Docker upstream selection, and use a
service-level DNS override only when a same-network probe proves that exact
resolver is reachable. This incident reached an earlier routing prerequisite:
there was no egress gateway at all.

Never hardcode a Brevo IP, edit a running container's `/etc/resolv.conf`, use host
networking, or disable firewall policy broadly.

## Controlled change and rollback

Before a daemon change, record `docker ps`, confirm restart policies, and create a
root-owned timestamped backup of `/etc/docker/daemon.json`. Validate edited JSON
before restarting Docker. A Docker restart affects running containers; do not run
`docker compose down` and do not remove volumes.

For this tracked Compose-only change, rollback by removing `egress` from the two
services and removing the top-level `egress` network declaration, then recreate
only the affected services:

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
