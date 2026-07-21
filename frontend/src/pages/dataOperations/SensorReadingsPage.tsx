import { useEffect, useState, type ReactElement } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import {
  getFactory,
  getMachine,
  getSensor,
  type Factory,
  type Machine,
  type PaginatedResponse,
  type Sensor,
} from "../../api/hierarchy";
import {
  listSensorReadings,
  type ReadingQuality,
  type ReadingSource,
  type SensorReading,
} from "../../api/sensorData";
import { useAuth } from "../../auth/useAuth";
import { CsvUploadDialog } from "../../components/dataOperations/CsvUploadDialog";
import { ReadingFormDialog } from "../../components/dataOperations/ReadingFormDialog";
import {
  Breadcrumbs,
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { StatusBadge, type StatusBadgeStatus } from "../../components/StatusBadge";
import { TrendChart } from "../../components/ui/TrendChart";
import { formatDate, hierarchyError } from "../hierarchy/shared";

const PAGE_SIZE = 20;
const inputClassName = "mt-2 rounded-md border border-neutral-300 px-3 py-2 text-sm";

function qualityStatus(quality: ReadingQuality): StatusBadgeStatus {
  return { BAD: "critical", GOOD: "healthy", MISSING: "inactive", OUTLIER: "warning" }[
    quality
  ] as StatusBadgeStatus;
}

function optionalIsoDate(value: string): string | undefined {
  if (value === "") return undefined;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString();
}

export function SensorReadingsPage(): ReactElement {
  const { factoryId = "", machineId = "", sensorId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { role } = useAuth();
  const canWrite = role === "admin" || role === "engineer";
  const [factory, setFactory] = useState<Factory | null>(null);
  const [machine, setMachine] = useState<Machine | null>(null);
  const [sensor, setSensor] = useState<Sensor | null>(null);
  const [page, setPage] = useState<PaginatedResponse<SensorReading> | null>(null);
  const [offset, setOffset] = useState(0);
  const [quality, setQuality] = useState<ReadingQuality | "">("");
  const [source, setSource] = useState<ReadingSource | "">("");
  const [timestampFrom, setTimestampFrom] = useState("");
  const [timestampTo, setTimestampTo] = useState("");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [appliedFilters, setAppliedFilters] = useState({
    quality: undefined as ReadingQuality | undefined,
    source: undefined as ReadingSource | undefined,
    timestampFrom: undefined as string | undefined,
    timestampTo: undefined as string | undefined,
    sortOrder: "desc" as "asc" | "desc",
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [showReading, setShowReading] = useState(
    canWrite && searchParams.get("action") === "add",
  );
  const [showUpload, setShowUpload] = useState(
    canWrite && searchParams.get("action") === "upload",
  );
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getFactory(factoryId, controller.signal),
      getMachine(machineId, controller.signal),
      getSensor(sensorId, controller.signal),
      listSensorReadings(sensorId, {
        ...appliedFilters,
        limit: PAGE_SIZE,
        offset,
        signal: controller.signal,
      }),
    ])
      .then(([factoryItem, machineItem, sensorItem, readingPage]) => {
        if (
          machineItem.factory_id !== factoryItem.id ||
          sensorItem.machine_id !== machineItem.id
        )
          throw new Error("This sensor does not belong to the requested hierarchy.");
        if (active) {
          setFactory(factoryItem);
          setMachine(machineItem);
          setSensor(sensorItem);
          setPage(readingPage);
          setLoading(false);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(hierarchyError(caught));
          setLoading(false);
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [appliedFilters, factoryId, machineId, offset, revision, sensorId]);

  const refresh = (): void => {
    setLoading(true);
    setError(null);
    setRevision((value) => value + 1);
  };
  const closeDialogs = (): void => {
    setShowReading(false);
    setShowUpload(false);
    setSearchParams({}, { replace: true });
  };
  if (loading) return <LoadingSkeleton label="Loading sensor readings" />;
  if (error !== null || factory === null || machine === null || sensor === null)
    return (
      <InlineError
        message={error ?? "Sensor readings are unavailable."}
        onRetry={refresh}
      />
    );

  return (
    <section aria-labelledby="readings-heading">
      <Breadcrumbs
        items={[
          { label: "Factories", to: "/factories" },
          { label: factory.name, to: `/factories/${factory.id}` },
          {
            label: machine.name,
            to: `/factories/${factory.id}/machines/${machine.id}`,
          },
          {
            label: sensor.name,
            to: `/factories/${factory.id}/machines/${machine.id}/sensors/${sensor.id}`,
          },
          { label: "Readings" },
        ]}
      />
      <div className="flex flex-col gap-4 border-b border-neutral-200 pb-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-purple-700">
            {sensor.name}
          </p>
          <h2
            className="mt-2 text-3xl font-semibold tracking-tight"
            id="readings-heading"
          >
            Sensor readings
          </h2>
          <p className="mt-2 text-sm text-neutral-600">
            Newest readings appear first by default
            {sensor.unit === null ? "." : ` · Unit: ${sensor.unit}.`}
          </p>
        </div>
        {canWrite ? (
          <div className="flex flex-wrap gap-2">
            <button
              className={secondaryButtonClassName}
              onClick={() => setShowReading(true)}
              type="button"
            >
              Add reading
            </button>
            <button
              className={primaryButtonClassName}
              onClick={() => setShowUpload(true)}
              type="button"
            >
              Upload CSV
            </button>
          </div>
        ) : null}
      </div>
      {message === null ? null : (
        <p
          className="mt-5 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
          role="status"
        >
          {message}
        </p>
      )}
      <div className="mt-6">
        <div className="mb-3">
          <h3 className="text-lg font-semibold text-neutral-950">Reading trend</h3>
          <p className="mt-1 text-sm text-neutral-600">
            The current filtered page, ordered chronologically for analysis.
          </p>
        </div>
        <TrendChart
          ariaLabel={`${sensor.name} sensor reading trend`}
          points={(page?.items ?? [])
            .slice()
            .sort(
              (left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp),
            )
            .map((reading) => ({
              label: new Date(reading.timestamp).toLocaleString(),
              value: reading.value,
            }))}
          unit={sensor.unit}
        />
      </div>
      <form
        className="mt-6 grid gap-3 rounded-lg border border-neutral-200 bg-white p-4 sm:grid-cols-2 lg:grid-cols-5"
        onSubmit={(event) => {
          event.preventDefault();
          setLoading(true);
          setError(null);
          setOffset(0);
          setAppliedFilters({
            quality: quality === "" ? undefined : quality,
            source: source === "" ? undefined : source,
            timestampFrom: optionalIsoDate(timestampFrom),
            timestampTo: optionalIsoDate(timestampTo),
            sortOrder,
          });
        }}
      >
        <div>
          <label className="block text-sm font-medium" htmlFor="readings-quality">
            Quality
          </label>
          <select
            className={inputClassName}
            id="readings-quality"
            onChange={(event) => setQuality(event.target.value as ReadingQuality | "")}
            value={quality}
          >
            <option value="">All</option>
            <option value="GOOD">Good</option>
            <option value="BAD">Bad</option>
            <option value="MISSING">Missing</option>
            <option value="OUTLIER">Outlier</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="readings-source">
            Source
          </label>
          <select
            className={inputClassName}
            id="readings-source"
            onChange={(event) => setSource(event.target.value as ReadingSource | "")}
            value={source}
          >
            <option value="">All</option>
            <option value="API">API</option>
            <option value="CSV">CSV</option>
            <option value="SIMULATION">Simulation</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="readings-from">
            From
          </label>
          <input
            className={inputClassName}
            id="readings-from"
            onChange={(event) => setTimestampFrom(event.target.value)}
            type="datetime-local"
            value={timestampFrom}
          />
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="readings-to">
            To
          </label>
          <input
            className={inputClassName}
            id="readings-to"
            onChange={(event) => setTimestampTo(event.target.value)}
            type="datetime-local"
            value={timestampTo}
          />
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="readings-order">
            Order
          </label>
          <div className="flex gap-2">
            <select
              className={inputClassName}
              id="readings-order"
              onChange={(event) => setSortOrder(event.target.value as "asc" | "desc")}
              value={sortOrder}
            >
              <option value="desc">Newest first</option>
              <option value="asc">Oldest first</option>
            </select>
            <button
              className="mt-2 rounded-md bg-neutral-900 px-3 py-2 text-sm font-semibold text-white"
              type="submit"
            >
              Apply
            </button>
          </div>
        </div>
      </form>
      <div className="mt-5">
        {page === null || page.total === 0 ? (
          <EmptyState
            action={
              canWrite ? (
                <button
                  className={primaryButtonClassName}
                  onClick={() => setShowReading(true)}
                  type="button"
                >
                  Add reading
                </button>
              ) : undefined
            }
            description="No readings match the current sensor and filters."
            title="No readings"
          />
        ) : (
          <>
            <div className="overflow-x-auto rounded-lg border border-neutral-200 bg-white">
              <table className="min-w-full divide-y divide-neutral-200 text-left text-sm">
                <thead className="bg-neutral-50">
                  <tr>
                    <th className="px-4 py-3 font-semibold" scope="col">
                      Timestamp
                    </th>
                    <th className="px-4 py-3 font-semibold" scope="col">
                      Value
                    </th>
                    <th className="px-4 py-3 font-semibold" scope="col">
                      Quality
                    </th>
                    <th className="px-4 py-3 font-semibold" scope="col">
                      Source
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-200">
                  {page.items.map((reading) => (
                    <tr key={reading.id}>
                      <td className="whitespace-nowrap px-4 py-3">
                        {formatDate(reading.timestamp)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-medium">
                        {reading.value}
                        {sensor.unit === null ? "" : ` ${sensor.unit}`}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge
                          label={reading.quality}
                          status={qualityStatus(reading.quality)}
                        />
                      </td>
                      <td className="px-4 py-3">{reading.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <PaginationControls
              limit={page.limit}
              offset={page.offset}
              onPageChange={(nextOffset) => {
                setLoading(true);
                setError(null);
                setOffset(nextOffset);
              }}
              total={page.total}
            />
          </>
        )}
      </div>
      {showReading ? (
        <ReadingFormDialog
          onClose={closeDialogs}
          onCreated={() => {
            closeDialogs();
            setMessage("Reading added successfully.");
            setOffset(0);
            refresh();
          }}
          sensor={sensor}
        />
      ) : null}
      {showUpload ? (
        <CsvUploadDialog
          onClose={closeDialogs}
          onImported={() => {
            setMessage("CSV import finished. Readings have been refreshed.");
            setOffset(0);
            setRevision((value) => value + 1);
          }}
        />
      ) : null}
    </section>
  );
}
