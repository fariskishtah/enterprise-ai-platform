# Legal review checklist

This is a release gate, not legal advice. Record owner, qualified reviewer, UTC
approval date, version, and evidence for every applicable item.

- [ ] Contracting entity, addresses, contacts, governing law, and customer model are confirmed.
- [ ] Terms, privacy, cookies, data processing, refunds, billing, AI limitations,
      retention, and support texts are approved and internally consistent.
- [ ] Production data map, cookie inventory, subprocessors, transfers, security
      measures, retention automation, backup policy, and deletion behavior match text.
- [ ] Prices, currency, taxes, renewal, lifecycle, cancellation, refund, and Paymob
      disclosures match backend-authoritative behavior and commercial agreements.
- [ ] AI claims, intended/prohibited use, human oversight, and incident escalation
      are approved by legal, safety, engineering, and product owners.
- [ ] Required localization, accessibility, regional rights, regulator/customer
      notices, and record-retention duties are identified.
- [ ] Each document has an immutable version, effective date, change process, and
      publication owner; replaced versions remain retrievable for audit.
- [ ] Counsel decides which documents require explicit acceptance versus notice.
- [ ] If acceptance is required, backend persistence records document version,
      subject/company, UTC timestamp, source, and immutable audit event before UI launch.
- [ ] Placeholder banners and `unapproved-draft` labels are removed only after
      approved documents and any required acceptance workflow are deployed and tested.
