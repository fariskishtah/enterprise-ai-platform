import { useEffect, useState, type ReactElement } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  createSensor,
  deleteMachine,
  getFactory,
  getMachine,
  listSensors,
  updateMachine,
  type Factory,
  type Machine,
  type PaginatedResponse,
  type Sensor,
} from "../../api/hierarchy";
import { useAuth } from "../../auth/useAuth";
import { ConfirmDialog } from "../../components/hierarchy/Dialogs";
import {
  MachineFormDialog,
  SensorFormDialog,
} from "../../components/hierarchy/HierarchyForms";
import {
  Breadcrumbs,
  EmptyState,
  InlineError,
  LoadingSkeleton,
  PaginationControls,
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../../components/hierarchy/ResourceStates";
import { displayValue, formatDate, hierarchyError } from "./shared";

const PAGE_SIZE = 20;

export function MachineDetailPage(): ReactElement {
  const { factoryId = "", machineId = "" } = useParams();
  const navigate = useNavigate();
  const { role } = useAuth();
  const canWrite = role === "admin" || role === "engineer";
  const canDelete = role === "admin";
  const [factory, setFactory] = useState<Factory | null>(null);
  const [machine, setMachine] = useState<Machine | null>(null);
  const [sensors, setSensors] = useState<PaginatedResponse<Sensor> | null>(null);
  const [sensorOffset, setSensorOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<"machine" | "sensor" | null>(null);
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
      listSensors(machineId, {
        limit: PAGE_SIZE,
        offset: sensorOffset,
        signal: controller.signal,
      }),
    ])
      .then(([factoryItem, machineItem, sensorPage]) => {
        if (machineItem.factory_id !== factoryItem.id) {
          throw new Error("This machine does not belong to the requested factory.");
        }
        if (active) {
          setFactory(factoryItem);
          setMachine(machineItem);
          setSensors(sensorPage);
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
  }, [factoryId, machineId, revision, sensorOffset]);

  const reload = (): void => {
    setLoading(true);
    setError(null);
    setRevision((value) => value + 1);
  };

  if (loading) return <LoadingSkeleton label="Loading machine" />;
  if (error !== null || factory === null || machine === null) {
    return (
      <InlineError
        message={error ?? "Machine details are unavailable."}
        onRetry={reload}
      />
    );
  }

  return (
    <section aria-labelledby="machine-heading">
      <Breadcrumbs
        items={[
          { label: "Factories", to: "/factories" },
          { label: factory.name, to: `/factories/${factory.id}` },
          { label: machine.name },
        ]}
      />
      <div className="flex flex-col gap-4 border-b border-neutral-200 pb-6 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-purple-700">
            {factory.name}
          </p>
          <h2
            className="mt-2 text-3xl font-semibold tracking-tight"
            id="machine-heading"
          >
            {machine.name}
          </h2>
          <p className="mt-2 text-sm text-neutral-600">
            {displayValue(machine.serial_number)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canWrite ? (
            <button
              className={secondaryButtonClassName}
              onClick={() => setForm("machine")}
              type="button"
            >
              Edit machine
            </button>
          ) : null}
          {canDelete ? (
            <button
              className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
              onClick={() => setConfirmDelete(true)}
              type="button"
            >
              Remove machine
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
      <dl className="mt-6 grid gap-4 rounded-lg border border-neutral-200 bg-white p-5 sm:grid-cols-2 lg:grid-cols-3">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Serial number
          </dt>
          <dd className="mt-1 text-sm font-medium">
            {displayValue(machine.serial_number)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Manufacturer
          </dt>
          <dd className="mt-1 text-sm font-medium">
            {displayValue(machine.manufacturer)}
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Model
          </dt>
          <dd className="mt-1 text-sm font-medium">{displayValue(machine.model)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Created
          </dt>
          <dd className="mt-1 text-sm font-medium">{formatDate(machine.created_at)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Updated
          </dt>
          <dd className="mt-1 text-sm font-medium">{formatDate(machine.updated_at)}</dd>
        </div>
      </dl>

      <div className="mt-8 flex items-center justify-between gap-4">
        <div>
          <h3 className="text-xl font-semibold">Sensors</h3>
          <p className="mt-1 text-sm text-neutral-600">
            Active sensors assigned to this machine.
          </p>
        </div>
        {canWrite ? (
          <button
            className={primaryButtonClassName}
            onClick={() => setForm("sensor")}
            type="button"
          >
            Add sensor
          </button>
        ) : null}
      </div>
      <div className="mt-4">
        {sensors === null || sensors.total === 0 ? (
          <EmptyState
            action={
              canWrite ? (
                <button
                  className={primaryButtonClassName}
                  onClick={() => setForm("sensor")}
                  type="button"
                >
                  Add sensor
                </button>
              ) : undefined
            }
            description="No active sensors belong to this machine."
            title="No sensors yet"
          />
        ) : (
          <>
            <ul className="divide-y divide-neutral-200 overflow-hidden rounded-lg border border-neutral-200 bg-white">
              {sensors.items.map((sensor) => (
                <li
                  className="flex flex-col gap-3 border-l-[3px] border-l-transparent p-4 transition hover:border-l-purple-500 hover:bg-purple-50 sm:flex-row sm:items-center sm:justify-between"
                  key={sensor.id}
                >
                  <div>
                    <h4 className="font-semibold text-neutral-950">{sensor.name}</h4>
                    <p className="mt-1 text-sm text-neutral-600">
                      {sensor.sensor_type ?? "Type not provided"}
                      {sensor.unit === null ? "" : ` · ${sensor.unit}`}
                    </p>
                  </div>
                  <Link
                    className="text-sm font-semibold text-purple-700 hover:underline"
                    to={`/factories/${factory.id}/machines/${machine.id}/sensors/${sensor.id}`}
                  >
                    Open sensor
                  </Link>
                </li>
              ))}
            </ul>
            <PaginationControls
              limit={sensors.limit}
              offset={sensors.offset}
              onPageChange={(nextOffset) => {
                setLoading(true);
                setError(null);
                setSensorOffset(nextOffset);
              }}
              total={sensors.total}
            />
          </>
        )}
      </div>

      {form === "machine" ? (
        <MachineFormDialog
          factory={factory}
          initial={machine}
          onClose={() => setForm(null)}
          onSave={async (payload) => {
            const updated = await updateMachine(machine.id, payload);
            setMachine(updated);
            setForm(null);
            setMessage("Machine updated successfully.");
            reload();
          }}
        />
      ) : null}
      {form === "sensor" ? (
        <SensorFormDialog
          machine={machine}
          onClose={() => setForm(null)}
          onSave={async (payload) => {
            await createSensor(payload);
            setForm(null);
            setMessage("Sensor added successfully.");
            setSensorOffset(0);
            reload();
          }}
        />
      ) : null}
      {confirmDelete ? (
        <ConfirmDialog
          busy={deleteBusy}
          error={deleteError}
          name={machine.name}
          onCancel={() => {
            if (!deleteBusy) {
              setConfirmDelete(false);
              setDeleteError(null);
            }
          }}
          onConfirm={() => {
            setDeleteBusy(true);
            setDeleteError(null);
            void deleteMachine(machine.id)
              .then(() => navigate(`/factories/${factory.id}`, { replace: true }))
              .catch((caught: unknown) => {
                setDeleteError(hierarchyError(caught));
                setDeleteBusy(false);
              });
          }}
          resourceLabel="machine"
        />
      ) : null}
    </section>
  );
}
