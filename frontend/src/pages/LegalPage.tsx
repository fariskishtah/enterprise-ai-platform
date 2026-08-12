import type { ReactElement } from "react";
import { Link, useParams } from "react-router-dom";

import { LegalFooter } from "../components/LegalFooter";
import { legalLinks } from "../components/legalLinks";

interface LegalDocument {
  readonly title: string;
  readonly purpose: string;
  readonly topics: readonly string[];
}

const documents: Readonly<Record<string, LegalDocument>> = {
  "ai-limitations": {
    purpose:
      "Describe intended use, human oversight, uncertainty, prohibited reliance, and reporting of unsafe outputs.",
    title: "AI limitations disclosure",
    topics: [
      "Intended use",
      "Human review",
      "Accuracy and uncertainty",
      "Prohibited reliance",
    ],
  },
  billing: {
    purpose:
      "Disclose plan price, currency, taxes, billing cycle, renewal, hosted checkout, and entitlement timing.",
    title: "Subscription billing disclosure",
    topics: ["Price and currency", "Renewal", "Taxes", "Payment processing"],
  },
  cookies: {
    purpose:
      "Classify essential session and security cookies and any optional technologies actually deployed.",
    title: "Cookie policy",
    topics: ["Essential cookies", "Retention", "Cookie controls", "Third parties"],
  },
  "data-processing": {
    purpose:
      "Define controller/processor roles, instructions, subprocessors, safeguards, assistance, and deletion.",
    title: "Data processing terms",
    topics: [
      "Roles and instructions",
      "Security",
      "Subprocessors",
      "Return and deletion",
    ],
  },
  "data-retention": {
    purpose:
      "State approved retention and deletion periods for account, industrial, AI, billing, support, audit, and backup data.",
    title: "Data retention policy",
    topics: ["Retention schedule", "Deletion", "Legal holds", "Backup expiry"],
  },
  privacy: {
    purpose:
      "Explain personal-data categories, purposes, lawful bases, recipients, transfers, retention, rights, and contacts.",
    title: "Privacy policy",
    topics: [
      "Data and purposes",
      "Legal basis",
      "Sharing and transfers",
      "Individual rights",
    ],
  },
  refunds: {
    purpose:
      "Define cancellation timing, service continuity, refund eligibility, exceptions, and the request process.",
    title: "Refund and cancellation policy",
    topics: ["Cancellation", "Refund eligibility", "Processing time", "Disputes"],
  },
  support: {
    purpose:
      "Define supported channels, hours, severity handling, customer responsibilities, and exclusions.",
    title: "Support policy",
    topics: [
      "Channels and hours",
      "Severity",
      "Response targets",
      "Customer responsibilities",
    ],
  },
  terms: {
    purpose:
      "Define the service relationship, authorized use, account duties, intellectual property, warranty, liability, and termination.",
    title: "Terms of service",
    topics: [
      "Service and accounts",
      "Acceptable use",
      "Intellectual property",
      "Liability and termination",
    ],
  },
};

export function LegalPage(): ReactElement {
  const { documentSlug = "" } = useParams();
  const document = documents[documentSlug];

  if (document === undefined) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-canvas px-5 text-foreground">
        <div className="max-w-lg text-center">
          <h1 className="text-3xl font-semibold">Policy placeholder not found</h1>
          <Link
            className="mt-5 inline-block font-semibold text-purple-800 underline"
            to="/legal/terms"
          >
            Open the legal document index
          </Link>
        </div>
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-canvas text-foreground">
      <main className="mx-auto max-w-4xl px-5 py-10 sm:px-8 sm:py-14">
        <Link
          className="text-sm font-bold uppercase tracking-[0.18em] text-purple-800"
          to="/"
        >
          FK SOLUTIONS
        </Link>
        <div
          className="mt-8 rounded-lg border border-amber-300 bg-amber-50 p-5 text-amber-950"
          role="note"
        >
          <p className="font-semibold">
            Draft placeholder — not approved for production
          </p>
          <p className="mt-2 text-sm leading-6">
            This page is not legal advice and does not create contractual terms. It
            requires review, completion, and approval by qualified counsel.
          </p>
        </div>
        <article className="mt-8 rounded-xl border border-border bg-card p-6 shadow-sm sm:p-9">
          <p className="text-sm font-semibold uppercase tracking-wider text-eyebrow">
            Version: unapproved-draft · Effective date: not set
          </p>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
            {document.title}
          </h1>
          <p className="mt-5 text-base leading-7 text-secondary-foreground">
            {document.purpose}
          </p>
          <h2 className="mt-9 text-xl font-semibold">Counsel must complete</h2>
          <ul className="mt-4 list-disc space-y-2 pl-6 text-sm leading-6 text-secondary-foreground">
            {document.topics.map((topic) => (
              <li key={topic}>{topic}</li>
            ))}
            <li>Applicable law, jurisdiction, company identity, and contact details</li>
            <li>Version, effective date, change notice, and acceptance requirements</li>
          </ul>
          <p className="mt-9 border-t border-border pt-6 text-sm leading-6 text-secondary-foreground">
            No acceptance is requested or recorded for this placeholder. Production
            launch requires an approved, versioned replacement and a reviewed decision
            on whether explicit acceptance must be persisted.
          </p>
        </article>
        <div className="mt-8 rounded-xl border border-purple-200 bg-purple-50/50 p-6 sm:p-7">
          <h2 className="text-lg font-semibold text-purple-950">
            Business & Technical Inquiries
          </h2>
          <p className="mt-1 text-sm text-secondary-foreground">
            For platform support, enterprise onboarding, or business partnerships, contact:
          </p>
          <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 text-sm font-medium">
            <span className="text-foreground">Faris Kishtah</span>
            <a
              className="text-purple-800 underline hover:text-purple-900"
              href="mailto:fkishtah@gmail.com"
            >
              fkishtah@gmail.com
            </a>
            <a
              className="text-purple-800 underline hover:text-purple-900"
              href="tel:+201115055205"
            >
              01115055205
            </a>
            <a
              className="text-purple-800 underline hover:text-purple-900"
              href="https://www.linkedin.com/in/faris-kishtah-59370b367"
              rel="noreferrer"
              target="_blank"
            >
              LinkedIn Profile
            </a>
          </div>
        </div>
        <nav aria-label="All legal documents" className="mt-8 flex flex-wrap gap-3">
          {legalLinks.map(([label, to]) => (
            <Link
              className="rounded-full border border-border-strong bg-card px-3 py-1.5 text-xs font-medium hover:border-purple-400"
              key={to}
              to={to}
            >
              {label}
            </Link>
          ))}
        </nav>
      </main>
      <LegalFooter />
    </div>
  );
}
