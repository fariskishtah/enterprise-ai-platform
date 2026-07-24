import { useEffect, useState, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { isRequestCancelled } from "../../api/client";
import { getCompany, type Company } from "../../api/hierarchy";
import { useAuth } from "../../auth/useAuth";
import {
  panelClassName,
  KeyValues,
} from "../../components/intelligence/IntelligenceUi";
import { PageHeader } from "../../components/ui/PageHeader";
import { useProductExperience } from "../../product/productExperience";

export function MyProfilePage(): ReactElement {
  const { user } = useAuth();
  const { mode } = useProductExperience();
  const [company, setCompany] = useState<Company | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user === null) return;
    const controller = new AbortController();
    void getCompany(user.company_id, controller.signal)
      .then((value) => {
        setCompany(value);
        setError(null);
      })
      .catch((caught: unknown) => {
        if (!isRequestCancelled(caught, controller.signal)) {
          setError(caught instanceof Error ? caught.message : "Company unavailable.");
        }
      });
    return () => controller.abort();
  }, [user]);

  return (
    <section aria-labelledby="profile-page-heading">
      <PageHeader
        description="Your authenticated account identity, access level, and workspace."
        eyebrow="Account"
        headingId="profile-page-heading"
        title="My Profile"
      />
      <section className={`${panelClassName} mt-6 max-w-3xl`}>
        {error ? (
          <p className="mb-4 rounded-md border border-danger-200 bg-danger-50 p-3 text-sm text-danger-800">
            Company details could not be loaded. Your account details remain available.
          </p>
        ) : null}
        <KeyValues
          items={[
            { label: "Full name", value: user?.full_name ?? "Not provided" },
            { label: "Email", value: user?.email ?? "Unavailable" },
            { label: "Role", value: user?.role ?? "Unavailable" },
            { label: "Company", value: company?.name ?? "Loading…" },
            {
              label: "Account status",
              value: user?.is_active ? "Active" : "Inactive",
            },
            { label: "Product mode", value: mode === "simple" ? "Simple" : "Expert" },
          ]}
        />
        <div className="mt-6 border-t border-border pt-5">
          <Link
            className="text-sm font-semibold text-link hover:text-link-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            to="/settings#change-password"
          >
            Change password and manage sessions
          </Link>
        </div>
      </section>
    </section>
  );
}
