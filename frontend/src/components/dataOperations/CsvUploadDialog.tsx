import { useState, type FormEvent, type ReactElement } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../api/client";
import {
  createUploadJob,
  getUploadJob,
  uploadCsvFile,
  type UploadJob,
} from "../../api/sensorData";
import { Dialog } from "../hierarchy/Dialogs";
import {
  primaryButtonClassName,
  secondaryButtonClassName,
  InlineNotice,
} from "../hierarchy/ResourceStates";
import { UploadJobSummary } from "./UploadJobSummary";

export function CsvUploadDialog({
  onClose,
  onImported,
}: {
  readonly onClose: () => void;
  readonly onImported: () => void;
}): ReactElement {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadJob | null>(null);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setError(null);
    setResult(null);
    if (file === null || !file.name.toLowerCase().endsWith(".csv")) {
      setError("Select a CSV file to continue.");
      return;
    }
    if (file.name.length > 255) {
      setError("The filename must be 255 characters or fewer.");
      return;
    }
    setBusy(true);
    let job: UploadJob | null = null;
    try {
      job = await createUploadJob(file.name);
      const imported = await uploadCsvFile(job.id, file);
      setResult(imported);
      onImported();
    } catch (caught) {
      if (job !== null) {
        try {
          setResult(await getUploadJob(job.id));
        } catch {
          // Preserve the original actionable upload error.
        }
      }
      setError(
        caught instanceof ApiError ? caught.message : "The CSV could not be imported.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      description="CSV submission immediately validates and imports accepted rows. This operation has no preview step."
      onClose={onClose}
      title="Upload sensor readings CSV"
    >
      {result === null ? (
        <form onSubmit={submit}>
          <div className="rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950">
            <p className="font-semibold">Immediate import</p>
            <p className="mt-1 leading-6">
              Selecting “Upload and import CSV” immediately processes the file. Required
              columns: <code>sensor_id</code>, <code>timestamp</code>,{" "}
              <code>value</code>. Optional column: <code>quality</code>.
            </p>
          </div>
          {error === null ? null : (
            <p
              className="mt-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
              role="alert"
            >
              {error}
            </p>
          )}
          <div className="mt-5">
            <label
              className="block text-sm font-medium text-neutral-800"
              htmlFor="csv-file"
            >
              CSV file
            </label>
            <input
              accept=".csv,text/csv"
              className="mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-neutral-100 file:px-3 file:py-2 file:font-semibold"
              disabled={busy}
              id="csv-file"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              required
              type="file"
            />
            {file === null ? null : (
              <p className="mt-2 text-sm text-neutral-600">
                {file.name} · {file.size.toLocaleString()} bytes
              </p>
            )}
          </div>
          <div className="mt-7 flex justify-end gap-3 border-t border-neutral-200 pt-5">
            <button
              className={secondaryButtonClassName}
              disabled={busy}
              onClick={onClose}
              type="button"
            >
              Cancel
            </button>
            <button
              className={primaryButtonClassName}
              disabled={busy || file === null}
              type="submit"
            >
              {busy ? "Uploading and importing…" : "Upload and import CSV"}
            </button>
          </div>
        </form>
      ) : (
        <div>
          {error === null ? null : (
            <p
              className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
              role="alert"
            >
              {error}
            </p>
          )}
          <UploadJobSummary job={result} />
          <div className="mt-4">
            <InlineNotice>
              Row-level rejection details and sensor data-quality metrics are not
              available from the current backend API.
            </InlineNotice>
          </div>
          <div className="mt-6 flex flex-wrap justify-end gap-3">
            <Link className={secondaryButtonClassName} to="/sensor-data/uploads">
              All upload jobs
            </Link>
            <button
              className={secondaryButtonClassName}
              onClick={() => {
                setFile(null);
                setResult(null);
                setError(null);
              }}
              type="button"
            >
              Upload another file
            </button>
            <button className={primaryButtonClassName} onClick={onClose} type="button">
              Done
            </button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
