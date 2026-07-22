import { useEffect, useState, type ReactElement } from "react";

import { isRequestCancelled } from "../../api/client";
import { listAllDatasetVersions, listDatasets } from "../../api/datasets";
import { secondaryButtonClassName } from "../hierarchy/ResourceStates";

const DATASET_PAGE_SIZE = 20;

interface ReadyTabularVersion {
  readonly datasetName: string;
  readonly id: string;
  readonly versionNumber: number;
  readonly rowCount: number | null;
  readonly columnCount: number | null;
}

export function RegisteredDatasetVersionSelect({
  disabled = false,
  id,
  onChange,
  value,
}: {
  readonly disabled?: boolean;
  readonly id: string;
  readonly onChange: (value: string) => void;
  readonly value: string;
}): ReactElement {
  const [options, setOptions] = useState<readonly ReadyTabularVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [datasetOffset, setDatasetOffset] = useState(0);
  const [datasetTotal, setDatasetTotal] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const load = async (): Promise<void> => {
      setLoading(true);
      setError(null);
      try {
        const datasets = await listDatasets({
          kind: "tabular",
          limit: DATASET_PAGE_SIZE,
          offset: datasetOffset,
          signal: controller.signal,
          status: "active",
        });
        const versionPages = await Promise.all(
          datasets.items.map(async (dataset) => ({
            dataset,
            versions: await listAllDatasetVersions(dataset.id, {
              signal: controller.signal,
            }),
          })),
        );
        if (controller.signal.aborted) return;
        setDatasetTotal(datasets.total);
        setOptions(
          versionPages.flatMap(({ dataset, versions }) =>
            versions
              .filter((version) => version.status === "ready")
              .map((version) => ({
                columnCount: version.column_count,
                datasetName: dataset.name,
                id: version.id,
                rowCount: version.row_count,
                versionNumber: version.version_number,
              })),
          ),
        );
        setLoading(false);
      } catch (caught) {
        if (!isRequestCancelled(caught, controller.signal)) {
          setError(
            caught instanceof Error
              ? caught.message
              : "Unable to load registered dataset versions.",
          );
          setLoading(false);
        }
      }
    };
    void load();
    return () => controller.abort();
  }, [datasetOffset, revision]);

  return (
    <div>
      <label className="block text-sm font-medium" htmlFor={id}>
        Ready dataset version
      </label>
      <select
        aria-describedby={`${id}-help`}
        className="mt-1 w-full rounded-md border border-border-strong bg-elevated px-3 py-2 text-sm"
        disabled={disabled || loading || error !== null || options.length === 0}
        id={id}
        onChange={(event) => onChange(event.target.value)}
        required
        value={value}
      >
        <option value="">
          {loading
            ? "Loading ready versions…"
            : options.length === 0
              ? "No ready tabular versions"
              : "Select a registered version"}
        </option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.datasetName} · version {option.versionNumber}
            {option.rowCount === null ? "" : ` · ${option.rowCount} rows`}
            {option.columnCount === null ? "" : ` · ${option.columnCount} columns`}
          </option>
        ))}
      </select>
      <p className="mt-1 text-xs text-muted-foreground" id={`${id}-help`}>
        Only immutable, ready tabular versions are available. The backend resolves its
        registered target and held-out evaluation split.
      </p>
      {error === null ? null : (
        <div
          className="mt-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800"
          role="alert"
        >
          <p>{error}</p>
          <button
            className="mt-2 font-semibold underline underline-offset-2"
            disabled={disabled}
            onClick={() => setRevision((current) => current + 1)}
            type="button"
          >
            Retry dataset discovery
          </button>
        </div>
      )}
      {!loading && error === null && options.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground" role="status">
          Create and process a tabular dataset version before selecting registered data.
        </p>
      ) : null}
      {datasetTotal > DATASET_PAGE_SIZE ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className="text-muted-foreground">
            Datasets {datasetOffset + 1}–
            {Math.min(datasetOffset + DATASET_PAGE_SIZE, datasetTotal)} of{" "}
            {datasetTotal}
          </span>
          <div className="flex gap-2">
            <button
              className={secondaryButtonClassName}
              disabled={disabled || loading || datasetOffset === 0}
              onClick={() => {
                onChange("");
                setLoading(true);
                setDatasetOffset((current) => Math.max(0, current - DATASET_PAGE_SIZE));
              }}
              type="button"
            >
              Previous datasets
            </button>
            <button
              className={secondaryButtonClassName}
              disabled={
                disabled || loading || datasetOffset + DATASET_PAGE_SIZE >= datasetTotal
              }
              onClick={() => {
                onChange("");
                setLoading(true);
                setDatasetOffset((current) => current + DATASET_PAGE_SIZE);
              }}
              type="button"
            >
              Next datasets
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
