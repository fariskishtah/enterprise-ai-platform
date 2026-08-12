---
name: factorymind-product-release
description: Guide FactoryMind product design, UX hardening, engineering changes, acceptance, and release preparation. Use for FactoryMind navigation, onboarding, factory workflows, AI/RAG behavior, billing UX, operational safety, production readiness, or release work where simplicity, tenant isolation, and protected production controls must remain explicit.
---

# FactoryMind Product and Release

## Work in focused phases

1. Establish the current checkpoint and reuse accepted evidence.
2. Inspect only the files and runtime state required by the active phase.
3. Explain each proposed feature or change in terms of a real factory user's goal.
4. Implement incrementally without weakening authorization or tenant isolation.
5. Run targeted checks for changed behavior. Run broad suites only when risk or code scope requires them.
6. Stop at phase boundaries and report changes, evidence, remaining problems, and the recommended next phase.

## Design for factory users

- Assume owners, managers, operators, and viewers are not ML engineers.
- Prefer plain manufacturing language, one clear next action, and useful empty states.
- Use progressive disclosure. Keep primary workflows prominent and advanced controls available without dominating the first-run experience.
- Group navigation by user intent, make groups collapsible, and adapt visibility to role and responsibility.
- Do not remove capabilities merely to simplify navigation.
- Treat navigation visibility as presentation only; preserve server-side authorization.
- Avoid duplicate concepts, unexplained actions, dead ends, and dashboards that present every metric at once.
- Check desktop and mobile behavior for navigation changes.

## Protect production and commercial state

- Treat production as protected. Do not perform destructive production actions or modify production data without explicit authorization.
- Keep `PAYMENT_PROVIDER=disabled` in production unless payment activation is separately and explicitly authorized.
- Never expose credentials, tokens, provider identifiers, or other secrets.
- Preserve databases, volumes, audit evidence, and protected artifacts.
- Prefer roll-forward changes and targeted service recreation. Never use a production-wide `docker compose down` as a routine deployment step.

## Preserve product and AI integrity

- Require a clear user purpose, helpful success/error states, and a discoverable next action for every feature.
- Keep role-aware journeys coherent for Owner, Admin, Engineer, Operator, Analyst, and Viewer.
- Ground AI answers in authorized tenant content only.
- Require source attribution where applicable, refuse unsupported answers, and keep cross-tenant leakage at zero.
- Do not accept endpoint availability alone as proof of AI quality; use deterministic grounded evaluations.

## Validate efficiently

- Use targeted searches before opening files and avoid unrelated repository scans.
- Preserve unrelated working-tree changes.
- Run affected unit, contract, and focused browser tests after changes.
- Reuse previously passed billing, auth, RBAC, email, and isolation evidence unless the change can invalidate it.
- Distinguish code defects from tooling gaps and operational approvals.
