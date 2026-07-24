# Tenant and Identity Model

## Controlled-pilot boundary

For the 0.9 controlled pilot, `Company` is the tenant root. A user belongs to
exactly one company through a non-null `users.company_id` foreign key. The
application does not expose a platform super-administrator, tenant switching,
cross-tenant sharing, or multi-company user membership.

This is a conservative single-customer deployment model with database-enforced
foreign keys, explicit company identifiers on business roots, request-scoped ORM
query guards, and service/repository authorization. It is not a claim of general
multi-tenant SaaS certification.

## Roles

- **Administrator** manages the company identity lifecycle, company settings,
  audit export, model champion promotion, alert resolution, and other destructive
  or privileged controls. An administrator cannot remove the last active
  administrator.
- **Engineer** manages manufacturing resources and data, trains and evaluates
  models, builds knowledge bases, runs governed predictions, and investigates
  monitoring state.
- **Operator** has read-oriented manufacturing and operational access, can run
  an approved structured prediction, and can acknowledge a pilot risk/alert.
  Operators cannot administer users, train models, or resolve alerts.

Administrators have company-wide access, not platform-wide access. Dataset and
RAG collaboration inside one company is supported where the service policy
allows it; owner identifiers remain lineage, not a tenant boundary.

## Resource scope

The following roots carry a non-null company identifier:

- users, factories, datasets, upload jobs, and experiments;
- training jobs, AutoML studies, model-promotion audit records;
- prediction events, reference profiles, monitoring evaluations, alerts,
  prediction outcomes, retraining policies/requests/audits;
- knowledge bases and RAG conversations;
- model feature schemas, machine-risk assessments, and unified audit events.

Companies own factories. Machines inherit their boundary from a factory,
sensors from a machine, readings from a sensor, and dataset versions/documents
from a dataset. Model ownership is established by the successful tenant-owned
training job for the exact registered model name and version. Feature schemas
may reference only a dataset version owned by the same company. Knowledge-base
attachments require a company-authorized ready document dataset version.

Monitoring and prediction records derive company scope from the authenticated
requester and exact model lineage. Alerts derive it from the monitoring
evaluation or registered model and the pilot additionally stores factory and
machine association.

## Enforcement

Authenticated requests bind the user's company to a context-local SQLAlchemy
SELECT guard. Repositories and services also use explicit company filters for
security-sensitive lookups and resource creation. Mutation routes resolve a
resource through a tenant-scoped read before state-changing updates where
needed. Authorization-neutral `404` responses conceal identifiers owned by a
different company.

Negative acceptance tests prove that Company B cannot manage Company A users,
read Company A machines, discover Company A feature schemas, or read Company A
machine-risk records. Dataset, training, AutoML, RAG, and manufacturing tests
exercise the same company boundary.

## Account lifecycle

Passwords are hashed using the existing password hasher. Reset credentials are
random, stored only as SHA-256 digests, expire after a bounded interval, and are
single use. Password change/reset and user deactivation revoke active refresh
tokens. Users can list session metadata, revoke one session, and revoke all
other sessions. Raw access, refresh, and reset tokens are excluded from audit
metadata and logs.

Production requires an outbound password-reset email adapter. The raw reset
credential can be returned only when
`EXPOSE_LOCAL_PASSWORD_RESET_TOKEN=true` and the environment is local,
development, or test.

## Unsupported enterprise identity capabilities

The pilot does not provide MFA, OIDC/SAML SSO, SCIM, delegated tenant
administration, platform super-administration, company switching, invitations
with email delivery, domain claiming, or tenant self-service deletion. These
require separate threat modeling, product policy, and acceptance testing.

