import type { ReactElement } from "react";
import { Link } from "react-router-dom";

import { useTheme } from "../theme/ThemeContext";

const productAreas = [
  {
    description:
      "Organize factories, production assets, sensors, datasets, and quality findings in one tenant-isolated workspace.",
    title: "Connect operational context",
  },
  {
    description:
      "Guide teams from validated data through training, evaluation, model registration, and controlled predictions.",
    title: "Govern the AI lifecycle",
  },
  {
    description:
      "Ask questions against registered knowledge, receive cited answers, and get an explicit refusal when evidence is insufficient.",
    title: "Ground decisions in evidence",
  },
] as const;

const workflow = [
  "Factory data",
  "Quality and datasets",
  "Training and models",
  "Grounded knowledge",
  "Monitoring and reports",
] as const;

function BrandMark(): ReactElement {
  return (
    <span
      aria-hidden="true"
      className="grid h-10 w-10 grid-cols-2 gap-1 rounded-xl bg-white/10 p-2 ring-1 ring-white/20"
    >
      <span className="rounded-sm bg-white" />
      <span className="rounded-sm bg-violet-300" />
      <span className="rounded-sm bg-violet-300" />
      <span className="rounded-sm bg-white" />
    </span>
  );
}

function ArrowIcon(): ReactElement {
  return (
    <svg aria-hidden="true" className="h-4 w-4" fill="none" viewBox="0 0 24 24">
      <path
        d="m8 5 7 7-7 7"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
      />
    </svg>
  );
}

export function LandingPage(): ReactElement {
  const { resolvedTheme, setPreference } = useTheme();
  const nextTheme = resolvedTheme === "dark" ? "light" : "dark";

  return (
    <div className="min-h-screen bg-[var(--app-background)] text-[var(--text-primary)]">
      <header className="border-b border-white/10 bg-[#0b1023] text-white">
        <nav
          aria-label="Public navigation"
          className="mx-auto flex max-w-7xl items-center justify-between gap-5 px-5 py-4 sm:px-8 lg:px-12"
        >
          <Link
            aria-label="FactoryMind home"
            className="flex items-center gap-3 rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-violet-300"
            to="/"
          >
            <BrandMark />
            <span>
              <span className="block text-sm font-semibold tracking-wide">
                FactoryMind
              </span>
              <span className="block text-xs text-slate-300">by FK Solutions</span>
            </span>
          </Link>
          <div className="flex items-center gap-2 sm:gap-3">
            <Link
              className="hidden rounded-lg px-3 py-2 text-sm font-semibold text-slate-200 hover:bg-white/10 hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-300 sm:inline-flex"
              to="/pricing"
            >
              Pricing
            </Link>
            <button
              aria-label={`Use ${nextTheme} mode`}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-white/20 text-slate-200 hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-300"
              onClick={() => setPreference(nextTheme)}
              type="button"
            >
              {resolvedTheme === "dark" ? "☀" : "☾"}
            </button>
            <Link
              className="inline-flex min-h-10 items-center rounded-lg border border-white/25 px-3 py-2 text-sm font-semibold text-white hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-300 sm:px-4"
              to="/login"
            >
              Sign in
            </Link>
            <Link
              className="hidden min-h-10 items-center rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-violet-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-300 sm:inline-flex"
              to="/register"
            >
              Get started
            </Link>
          </div>
        </nav>
      </header>

      <main>
        <section className="relative overflow-hidden bg-[#0b1023] text-white">
          <div
            aria-hidden="true"
            className="absolute -left-32 top-12 h-96 w-96 rounded-full bg-violet-600/30 blur-3xl"
          />
          <div
            aria-hidden="true"
            className="absolute -right-40 bottom-0 h-96 w-96 rounded-full bg-indigo-400/20 blur-3xl"
          />
          <div className="relative mx-auto grid max-w-7xl gap-12 px-5 py-16 sm:px-8 sm:py-24 lg:grid-cols-[1.1fr_0.9fr] lg:items-center lg:px-12 lg:py-28">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-violet-300">
                Industrial AI · Operational intelligence
              </p>
              <h1 className="mt-5 max-w-4xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl lg:text-6xl">
                Turn trusted manufacturing data into grounded operational decisions.
              </h1>
              <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-300">
                FactoryMind gives manufacturing operations, reliability, and AI teams
                one secure workspace for factory context, governed model workflows,
                cited knowledge, monitoring, and reports.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link
                  className="inline-flex min-h-12 items-center justify-center gap-2 rounded-lg bg-violet-600 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-950/30 hover:bg-violet-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-300"
                  to="/register"
                >
                  Create account
                  <ArrowIcon />
                </Link>
                <a
                  className="inline-flex min-h-12 items-center justify-center rounded-lg border border-white/25 px-5 py-3 text-sm font-semibold text-white hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-violet-300"
                  href="mailto:fkishtah@gmail.com?subject=FactoryMind%20business%20inquiry"
                >
                  Request a demo
                </a>
              </div>
              <p className="mt-5 text-sm text-slate-400">
                Structured data onboarding · UTF-8 knowledge ingestion · Manual prepaid
                access renewal
              </p>
            </div>

            <div className="rounded-2xl border border-white/15 bg-white/[0.07] p-5 shadow-2xl shadow-black/20 backdrop-blur sm:p-7">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-violet-300">
                One connected workflow
              </p>
              <ol className="mt-5 space-y-3">
                {workflow.map((step, index) => (
                  <li
                    className="flex items-center gap-4 rounded-xl border border-white/10 bg-black/10 px-4 py-3"
                    key={step}
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-violet-400/20 text-sm font-semibold text-violet-200">
                      {index + 1}
                    </span>
                    <span className="font-medium text-slate-100">{step}</span>
                  </li>
                ))}
              </ol>
              <p className="mt-5 text-sm leading-6 text-slate-300">
                Factory → Machine / Production Asset → Sensor remains the canonical
                operating hierarchy.
              </p>
            </div>
          </div>
        </section>

        <section
          aria-labelledby="platform-capabilities"
          className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12"
        >
          <div className="max-w-3xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[var(--text-eyebrow)]">
              Built for manufacturing teams
            </p>
            <h2
              className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl"
              id="platform-capabilities"
            >
              A clear path from operational data to accountable action
            </h2>
            <p className="mt-4 text-base leading-7 text-[var(--text-secondary)]">
              Keep advanced tools available to engineers while giving owners, operators,
              analysts, and viewers role-appropriate access and context.
            </p>
          </div>
          <div className="mt-10 grid gap-5 md:grid-cols-3">
            {productAreas.map((area) => (
              <article
                className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-sm"
                key={area.title}
              >
                <h3 className="text-lg font-semibold">{area.title}</h3>
                <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">
                  {area.description}
                </p>
              </article>
            ))}
          </div>
        </section>

        <section className="border-y border-[var(--border)] bg-[var(--surface-secondary)]">
          <div className="mx-auto grid max-w-7xl gap-8 px-5 py-14 sm:px-8 md:grid-cols-2 lg:px-12">
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                Grounded by design
              </h2>
              <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">
                FactoryMind answers from authorized registered sources, includes
                citations, and explicitly refuses unsupported questions. Human review
                remains essential for operational decisions.
              </p>
            </div>
            <div>
              <h2 className="text-2xl font-semibold tracking-tight">
                Protected workspace boundaries
              </h2>
              <p className="mt-3 text-sm leading-6 text-[var(--text-secondary)]">
                Tenant-aware authorization, role controls, audit events, encrypted
                sessions, and private encrypted backups support the controlled
                production service.
              </p>
            </div>
          </div>
        </section>

        <section className="mx-auto max-w-7xl px-5 py-16 sm:px-8 sm:py-20 lg:px-12">
          <div className="rounded-2xl bg-[#171a2b] px-6 py-10 text-white sm:px-10 sm:py-12 lg:flex lg:items-center lg:justify-between lg:gap-10">
            <div>
              <h2 className="text-3xl font-semibold tracking-tight">
                Start with your manufacturing workspace
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                Create an account to begin, or contact FactoryMind for a focused
                business and product walkthrough.
              </p>
            </div>
            <div className="mt-6 flex flex-col gap-3 sm:flex-row lg:mt-0">
              <Link
                className="inline-flex min-h-11 items-center justify-center rounded-lg bg-violet-600 px-5 py-2.5 text-sm font-semibold hover:bg-violet-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-300"
                to="/register"
              >
                Get started
              </Link>
              <Link
                className="inline-flex min-h-11 items-center justify-center rounded-lg border border-white/25 px-5 py-2.5 text-sm font-semibold hover:bg-white/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-300"
                to="/login"
              >
                Sign in
              </Link>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-[var(--border)] bg-[var(--surface)]">
        <div className="mx-auto flex max-w-7xl flex-col gap-6 px-5 py-8 text-sm text-[var(--text-secondary)] sm:px-8 md:flex-row md:items-center md:justify-between lg:px-12">
          <div>
            <p className="font-semibold text-[var(--text-primary)]">FactoryMind</p>
            <p className="mt-1">Industrial AI for manufacturing operations.</p>
          </div>
          <nav
            aria-label="Business and product links"
            className="flex flex-wrap gap-x-5 gap-y-3"
          >
            <Link className="font-medium hover:text-[var(--text-link)]" to="/pricing">
              Pricing
            </Link>
            <a
              className="font-medium hover:text-[var(--text-link)]"
              href="mailto:fkishtah@gmail.com?subject=FactoryMind%20business%20inquiry"
            >
              Email
            </a>
            <a
              className="font-medium hover:text-[var(--text-link)]"
              href="tel:01115055205"
            >
              01115055205
            </a>
            <a
              className="font-medium hover:text-[var(--text-link)]"
              href="https://www.linkedin.com/in/faris-kishtah-59370b367"
              rel="noreferrer"
              target="_blank"
            >
              LinkedIn
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
