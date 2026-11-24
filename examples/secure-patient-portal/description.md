# Northwind Patient Portal: how we keep it secure

This is a plain-English description of a security setup, written the way you would explain it to a new member of the security team. No diagrams, no formal notation.

## Our network areas

We split our network into five areas:

- **Internet**: everything outside our company. Patients are here, and so are attackers.
- **DMZ**: the only area the internet is allowed to reach.
- **App zone**: where our own application runs. Nothing on the internet can reach it directly.
- **Data zone**: the most protected area. Only the app zone may talk to it.
- **Management zone**: where our admin and monitoring tools live.

## How patients get in

Patients open the Patient Portal in their browser. Their traffic first hits the Edge Firewall, which only allows HTTPS on port 443 and drops everything else.

Behind the firewall is a WAF (web application firewall). It blocks common web attacks and passes the clean requests on to the Portal App in the app zone, again over HTTPS.

## Signing in

The Portal App does not store passwords. It checks every login with Okta, which is a cloud service outside our network, using OIDC.

## Patient data and secrets

The Portal App reads and writes patient records in the Patient Database, which is in the data zone. That connection uses TLS on port 5432, and the database is encrypted on disk.

The database password is not kept in the application. The Portal App fetches it from the Secrets Vault, which is also in the data zone.

Nothing in the DMZ is ever allowed to talk to the data zone. If the WAF tried to reach the Patient Database, it would be blocked.

## How our admins get in

Admins never connect to servers straight from the internet. They connect to the VPN Gateway in the DMZ, which checks their login and second factor with Okta. From the VPN they land on the Bastion Host in the management zone. From the Bastion Host they can open an SSH session (port 22) to the Portal App servers.

## Watching for trouble

The Edge Firewall, the WAF, the Portal App and the Bastion Host all send their logs to our SIEM, which is Splunk, in the management zone. When Splunk sees something suspicious it alerts the Security Team.
