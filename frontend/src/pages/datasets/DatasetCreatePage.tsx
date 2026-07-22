import { useState, type FormEvent, type ReactElement } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  createDatasetRecord,
  createDatasetVersion,
  type DatasetKind,
} from "../../api/datasets";
import { LifecycleCard } from "../../components/dataRag/DataRagUi";
import {
  Breadcrumbs,
  InlineNotice,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { PageHeader } from "../../components/ui/PageHeader";
import { hierarchyError } from "../hierarchy/shared";

export function DatasetCreatePage(): ReactElement {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState<DatasetKind>("tabular");
  const [file, setFile] = useState<File | null>(null);
  const [targetColumn, setTargetColumn] = useState("");
  const [splitColumn, setSplitColumn] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    if (file === null) {
      setError("Select a supported file to register this dataset.");
      return;
    }
    if (file.name.length > 255) {
      setError("The filename must be 255 characters or fewer.");
      return;
    }
    const extension = file.name.toLowerCase();
    if (kind === "tabular" && !extension.endsWith(".csv")) {
      setError("Tabular datasets currently accept CSV files.");
      return;
    }
    if (kind === "document_collection" && !extension.endsWith(".txt")) {
      setError("Document collections currently accept plain text files.");
      return;
    }
    setSubmitting(true);
    try {
      const dataset = await createDatasetRecord({
        description: description.trim() || null,
        kind,
        name: name.trim(),
      });
      try {
        const version = await createDatasetVersion(dataset.id, file, {
          splitColumn: splitColumn.trim() || undefined,
          targetColumn: targetColumn.trim() || undefined,
        });
        navigate(`/datasets/${dataset.id}/versions/${version.id}`, {
          state: { notice: "Dataset registered and processing started." },
        });
      } catch (caught) {
        navigate(`/datasets/${dataset.id}`, {
          state: {
            notice: `The dataset registry entry was created, but its first version was not uploaded. Use Upload new version to retry. ${hierarchyError(caught)}`,
          },
        });
      }
    } catch (caught) {
      setError(hierarchyError(caught));
      setSubmitting(false);
    }
  };

  return (
    <section aria-labelledby="dataset-create-heading">
      <Breadcrumbs
        items={[{ label: "Dataset Registry", to: "/datasets" }, { label: "Register" }]}
      />
      <PageHeader
        description="Create an owner-scoped registry entry and its first immutable version from one bounded upload."
        eyebrow="Dataset Registry"
        headingId="dataset-create-heading"
        title="Register dataset"
      />
      <div className="mt-6 max-w-3xl">
        <InlineNotice>
          Files are validated and stored by the backend. Uploading starts processing
          immediately; no server filesystem path is exposed.
        </InlineNotice>
        <form className="mt-5" onSubmit={(event) => void submit(event)}>
          <LifecycleCard>
            <div className="grid gap-5 sm:grid-cols-2">
              <label className="text-sm font-medium text-foreground sm:col-span-2">
                Dataset name
                <input
                  autoComplete="off"
                  className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                  disabled={submitting}
                  maxLength={128}
                  minLength={3}
                  onChange={(event) => setName(event.target.value)}
                  required
                  value={name}
                />
              </label>
              <label className="text-sm font-medium text-foreground sm:col-span-2">
                Description (optional)
                <textarea
                  className="mt-1 min-h-24 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                  disabled={submitting}
                  maxLength={2000}
                  onChange={(event) => setDescription(event.target.value)}
                  value={description}
                />
              </label>
              <label className="text-sm font-medium text-foreground">
                Dataset kind
                <select
                  className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                  disabled={submitting}
                  onChange={(event) => {
                    setKind(event.target.value as DatasetKind);
                    setFile(null);
                  }}
                  value={kind}
                >
                  <option value="tabular">Tabular</option>
                  <option value="document_collection">Document collection</option>
                </select>
              </label>
              <label className="text-sm font-medium text-foreground">
                {kind === "tabular" ? "CSV file" : "Plain text file"}
                <input
                  accept={kind === "tabular" ? ".csv,text/csv" : ".txt,text/plain"}
                  className="mt-1 block w-full rounded-md border border-border-strong bg-elevated px-3 py-2 text-sm"
                  disabled={submitting}
                  key={kind}
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                  required
                  type="file"
                />
              </label>
              {kind === "tabular" ? (
                <>
                  <label className="text-sm font-medium text-foreground">
                    Target column (optional)
                    <input
                      className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                      disabled={submitting}
                      maxLength={128}
                      onChange={(event) => setTargetColumn(event.target.value)}
                      value={targetColumn}
                    />
                  </label>
                  <label className="text-sm font-medium text-foreground">
                    Split column (optional)
                    <input
                      className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2"
                      disabled={submitting}
                      maxLength={128}
                      onChange={(event) => setSplitColumn(event.target.value)}
                      value={splitColumn}
                    />
                  </label>
                </>
              ) : null}
            </div>
            {file === null ? null : (
              <p className="mt-4 text-sm text-muted-foreground">
                {file.name} · {file.size.toLocaleString()} bytes
              </p>
            )}
            {error === null ? null : (
              <p
                className="mt-5 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
                role="alert"
              >
                {error}
              </p>
            )}
            {submitting ? (
              <p
                aria-live="polite"
                className="mt-5 text-sm font-medium text-link"
                role="status"
              >
                Uploading and registering the immutable dataset version…
              </p>
            ) : null}
            <div className="mt-6 flex flex-wrap justify-end gap-3 border-t border-border pt-5">
              <Link className={secondaryButtonClassName} to="/datasets">
                Cancel
              </Link>
              <button
                className={primaryButtonClassName}
                disabled={submitting || file === null}
                type="submit"
              >
                {submitting ? "Registering…" : "Upload and register dataset"}
              </button>
            </div>
          </LifecycleCard>
        </form>
      </div>
    </section>
  );
}
