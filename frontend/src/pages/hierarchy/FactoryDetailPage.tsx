import { useEffect, useState, type ReactElement } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  createMachine,
  deleteFactory,
  getCompany,
  getFactory,
  listAllCompanies,
  listMachines,
  updateFactory,
  type Company,
  type Factory,
  type Machine,
  type PaginatedResponse,
} from "../../api/hierarchy";
import { useAuth } from "../../auth/useAuth";
import { ConfirmDialog } from "../../components/hierarchy/Dialogs";
import {
  FactoryFormDialog,
  MachineFormDialog,
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

export function FactoryDetailPage(): ReactElement {
  const { factoryId = "" } = useParams();
  const navigate = useNavigate();
  const { role } = useAuth();
  const canWrite = role === "admin" || role === "engineer";
  const canDelete = role === "admin";
  const [factory, setFactory] = useState<Factory | null>(null);
  const [company, setCompany] = useState<Company | null>(null);
  const [companies, setCompanies] = useState<readonly Company[]>([]);
  const [machines, setMachines] = useState<PaginatedResponse<Machine> | null>(null);
  const [machineOffset, setMachineOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [form, setForm] = useState<"factory" | "machine" | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    Promise.all([
      getFactory(factoryId, controller.signal),
      listMachines(factoryId, {
        limit: PAGE_SIZE,
        offset: machineOffset,
        signal: controller.signal,
      }),
      listAllCompanies(controller.signal),
    ])
      .then(async ([factoryItem, machinePage, companyItems]) => {
        const companyItem = await getCompany(factoryItem.company_id, controller.signal);
        if (active) {
          setFactory(factoryItem);
          setMachines(machinePage);
          setCompanies(companyItems);
          setCompany(companyItem);
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
  }, [factoryId, machineOffset, revision]);

  const reload = (): void => {
    setLoading(true);
    setError(null);
    setRevision((value) => value + 1);
  };

  if (loading) {
    return <LoadingSkeleton label="Loading factory" />;
  }
  if (error !== null || factory === null || company === null) {
    return (
      <InlineError
        message={error ?? "Factory details are unavailable."}
        onRetry={reload}
      />
    );
  }

  return (
    <section aria-labelledby="factory-heading">
      <Breadcrumbs
        items={[{ label: "Factories", to: "/factories" }, { label: factory.name }]}
      />
      <div className="flex flex-col gap-4 border-b border-neutral-200 pb-6 md:flex-row md:items-start md:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-teal-700">
            {company.name}
          </p>
          <h2
            className="mt-2 text-3xl font-semibold tracking-tight"
            id="factory-heading"
          >
            {factory.name}
          </h2>
          <p className="mt-2 text-sm text-neutral-600">
            {displayValue(factory.location)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {canWrite ? (
            <button
              className={secondaryButtonClassName}
              onClick={() => setForm("factory")}
              type="button"
            >
              Edit factory
            </button>
          ) : null}
          {canDelete ? (
            <button
              className="rounded-md border border-red-300 bg-white px-4 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
              onClick={() => setConfirmDelete(true)}
              type="button"
            >
              Remove factory
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
            Company
          </dt>
          <dd className="mt-1 text-sm font-medium">{company.name}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Location
          </dt>
          <dd className="mt-1 text-sm font-medium">{displayValue(factory.location)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Created
          </dt>
          <dd className="mt-1 text-sm font-medium">{formatDate(factory.created_at)}</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
            Updated
          </dt>
          <dd className="mt-1 text-sm font-medium">{formatDate(factory.updated_at)}</dd>
        </div>
        {factory.description === null ? null : (
          <div className="sm:col-span-2 lg:col-span-4">
            <dt className="text-xs font-semibold uppercase tracking-wider text-neutral-500">
              Description
            </dt>
            <dd className="mt-1 text-sm leading-6 text-neutral-700">
              {factory.description}
            </dd>
          </div>
        )}
      </dl>

      <div className="mt-8 flex items-center justify-between gap-4">
        <div>
          <h3 className="text-xl font-semibold">Machines</h3>
          <p className="mt-1 text-sm text-neutral-600">
            Active equipment assigned to this factory.
          </p>
        </div>
        {canWrite ? (
          <button
            className={primaryButtonClassName}
            onClick={() => setForm("machine")}
            type="button"
          >
            Add machine
          </button>
        ) : null}
      </div>
      <div className="mt-4">
        {machines === null || machines.total === 0 ? (
          <EmptyState
            action={
              canWrite ? (
                <button
                  className={primaryButtonClassName}
                  onClick={() => setForm("machine")}
                  type="button"
                >
                  Add machine
                </button>
              ) : undefined
            }
            description="No active machines belong to this factory."
            title="No machines yet"
          />
        ) : (
          <>
            <ul className="divide-y divide-neutral-200 overflow-hidden rounded-lg border border-neutral-200 bg-white">
              {machines.items.map((machine) => (
                <li
                  className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between"
                  key={machine.id}
                >
                  <div>
                    <h4 className="font-semibold text-neutral-950">{machine.name}</h4>
                    <p className="mt-1 text-sm text-neutral-600">
                      {machine.manufacturer ?? "Manufacturer not provided"}
                      {machine.model === null ? "" : ` · ${machine.model}`}
                    </p>
                  </div>
                  <Link
                    className="text-sm font-semibold text-teal-700 hover:underline"
                    to={`/factories/${factory.id}/machines/${machine.id}`}
                  >
                    Open machine
                  </Link>
                </li>
              ))}
            </ul>
            <PaginationControls
              limit={machines.limit}
              offset={machines.offset}
              onPageChange={(nextOffset) => {
                setLoading(true);
                setError(null);
                setMachineOffset(nextOffset);
              }}
              total={machines.total}
            />
          </>
        )}
      </div>

      {form === "factory" ? (
        <FactoryFormDialog
          companies={companies}
          initial={factory}
          onClose={() => setForm(null)}
          onSave={async (payload) => {
            const updated = await updateFactory(factory.id, payload);
            setFactory(updated);
            setForm(null);
            setMessage("Factory updated successfully.");
            reload();
          }}
        />
      ) : null}
      {form === "machine" ? (
        <MachineFormDialog
          factory={factory}
          onClose={() => setForm(null)}
          onSave={async (payload) => {
            await createMachine(payload);
            setForm(null);
            setMessage("Machine added successfully.");
            setMachineOffset(0);
            reload();
          }}
        />
      ) : null}
      {confirmDelete ? (
        <ConfirmDialog
          busy={deleteBusy}
          error={deleteError}
          name={factory.name}
          onCancel={() => {
            if (!deleteBusy) {
              setConfirmDelete(false);
              setDeleteError(null);
            }
          }}
          onConfirm={() => {
            setDeleteBusy(true);
            setDeleteError(null);
            void deleteFactory(factory.id)
              .then(() => navigate("/factories", { replace: true }))
              .catch((caught: unknown) => {
                setDeleteError(hierarchyError(caught));
                setDeleteBusy(false);
              });
          }}
          resourceLabel="factory"
        />
      ) : null}
    </section>
  );
}
