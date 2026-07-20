import { useEffect, useState, type ReactElement } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  deleteSensor,
  getFactory,
  getMachine,
  getSensor,
  updateSensor,
  type Factory,
  type Machine,
  type Sensor,
} from "../../api/hierarchy";
import { useAuth } from "../../auth/useAuth";
import { ConfirmDialog } from "../../components/hierarchy/Dialogs";
import { SensorFormDialog } from "../../components/hierarchy/HierarchyForms";
import {
  Breadcrumbs,
  InlineError,
  LoadingSkeleton,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { displayValue, formatDate, hierarchyError } from "./shared";

export function SensorDetailPage(): ReactElement {
  const { factoryId = "", machineId = "", sensorId = "" } = useParams();
  const navigate = useNavigate();
  const { role } = useAuth();
  const canWrite = role === "admin" || role === "engineer";
  const canDelete = role === "admin";
  const readingsPath = `/factories/${factoryId}/machines/${machineId}/sensors/${sensorId}/readings`;
  const [factory, setFactory] = useState<Factory | null>(null);
  const [machine, setMachine] = useState<Machine | null>(null);
  const [sensor, setSensor] = useState<Sensor | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getFactory(factoryId, controller.signal),
      getMachine(machineId, controller.signal),
      getSensor(sensorId, controller.signal),
    ])
      .then(([factoryItem, machineItem, sensorItem]) => {
        if (
          machineItem.factory_id !== factoryItem.id ||
          sensorItem.machine_id !== machineItem.id
        )
          throw new Error("This sensor does not belong to the requested hierarchy.");
        if (active) {
          setFactory(factoryItem);
          setMachine(machineItem);
          setSensor(sensorItem);
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
  }, [factoryId, machineId, revision, sensorId]);

  const reload = (): void => {
    setLoading(true);
    setError(null);
    setRevision((value) => value + 1);
  };
  if (loading) return <LoadingSkeleton label="Loading sensor" />;
  if (error !== null || factory === null || machine === null || sensor === null)
    return (
      <InlineError
        message={error ?? "Sensor details are unavailable."}
        onRetry={reload}
      />
    );

  return (
    <section aria-labelledby="sensor-heading">
      <Breadcrumbs
        items={[
          { label: "Factories", to: "/factories" },
          { label: factory.name, to: `/factories/${factory.id}` },
          {
            label: machine.name,
            to: `/factories/${factory.id}/machines/${machine.id}`,
          },
          { label: sensor.name },
        ]}
      />
      <div className="flex flex-col gap-4 border-b border-neutral-200 pb-6 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-teal-700">
            {machine.name}
          </p>
          <h2
            className="mt-2 text-3xl font-semibold tracking-tight"
            id="sensor-heading"
          >
            {sensor.name}
          </h2>
          <p className="mt-2 text-sm text-neutral-600">
            {sensor.sensor_type ?? "Sensor type not provided"}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canWrite ? (
            <button
              className={secondaryButtonClassName}
              onClick={() => setEditing(true)}
              type="button"
            >
              Edit sensor
            </button>
          ) : null}
          {canDelete ? (
            <button
              className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
              onClick={() => setConfirmDelete(true)}
              type="button"
            >
              Remove sensor
            </button>
          ) : null}
        </div>
      </div>
      {message === null ? null : (
        <p
          className="mt-5 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800"
          role="status"
        >
          {message}
        </p>
      )}
      <dl className="mt-6 grid gap-4 rounded-lg border border-neutral-200 bg-white p-5 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Type
          </dt>
          <dd className="mt-1 text-sm font-medium">
            {displayValue(sensor.sensor_type)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Unit
          </dt>
          <dd className="mt-1 text-sm font-medium">{displayValue(sensor.unit)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Sampling rate
          </dt>
          <dd className="mt-1 text-sm font-medium">{sensor.sampling_rate}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Configured range
          </dt>
          <dd className="mt-1 text-sm font-medium">
            {sensor.min_value} – {sensor.max_value}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Created
          </dt>
          <dd className="mt-1 text-sm font-medium">{formatDate(sensor.created_at)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Updated
          </dt>
          <dd className="mt-1 text-sm font-medium">{formatDate(sensor.updated_at)}</dd>
        </div>
        {sensor.description === null ? null : (
          <div className="sm:col-span-2 lg:col-span-4">
            <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
              Description
            </dt>
            <dd className="mt-1 text-sm leading-6 text-neutral-700">
              {sensor.description}
            </dd>
          </div>
        )}
      </dl>
      <section
        className="mt-6 rounded-lg border border-blue-200 bg-blue-50 p-5"
        aria-labelledby="sensor-readings-actions"
      >
        <h3 className="font-semibold text-blue-950" id="sensor-readings-actions">
          Sensor readings
        </h3>
        <p className="mt-1 text-sm leading-6 text-blue-900">
          Review timestamped values or add data using the operations supported by the
          current API.
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link className={secondaryButtonClassName} to={readingsPath}>
            View readings
          </Link>
          {canWrite ? (
            <Link
              className={secondaryButtonClassName}
              to={`${readingsPath}?action=add`}
            >
              Add reading
            </Link>
          ) : null}
          {canWrite ? (
            <Link
              className={secondaryButtonClassName}
              to={`${readingsPath}?action=upload`}
            >
              Upload CSV
            </Link>
          ) : null}
        </div>
      </section>
      {editing ? (
        <SensorFormDialog
          initial={sensor}
          machine={machine}
          onClose={() => setEditing(false)}
          onSave={async (payload) => {
            const updated = await updateSensor(sensor.id, payload);
            setSensor(updated);
            setEditing(false);
            setMessage("Sensor updated successfully.");
          }}
        />
      ) : null}
      {confirmDelete ? (
        <ConfirmDialog
          busy={deleteBusy}
          error={deleteError}
          name={sensor.name}
          onCancel={() => {
            if (!deleteBusy) {
              setConfirmDelete(false);
              setDeleteError(null);
            }
          }}
          onConfirm={() => {
            setDeleteBusy(true);
            setDeleteError(null);
            void deleteSensor(sensor.id)
              .then(() =>
                navigate(`/factories/${factory.id}/machines/${machine.id}`, {
                  replace: true,
                }),
              )
              .catch((caught: unknown) => {
                setDeleteError(hierarchyError(caught));
                setDeleteBusy(false);
              });
          }}
          resourceLabel="sensor"
        />
      ) : null}
    </section>
  );
}
