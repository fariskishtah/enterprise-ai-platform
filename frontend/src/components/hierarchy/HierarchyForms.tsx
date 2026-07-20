import { useState, type FormEvent, type ReactElement } from "react";

import { ApiError } from "../../api/client";
import type {
  Company,
  Factory,
  FactoryInput,
  Machine,
  MachineInput,
  Sensor,
  SensorInput,
} from "../../api/hierarchy";
import { Dialog } from "./Dialogs";
import { primaryButtonClassName, secondaryButtonClassName } from "./ResourceStates";

const inputClassName =
  "mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm outline-none focus:border-teal-700 focus:ring-2 focus:ring-teal-700/20 disabled:bg-neutral-100";
const labelClassName = "block text-sm font-medium text-neutral-800";

function optionalText(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function formError(error: unknown): string {
  return error instanceof ApiError ? error.message : "The resource could not be saved.";
}

function FormActions({
  busy,
  onCancel,
}: {
  readonly busy: boolean;
  readonly onCancel: () => void;
}): ReactElement {
  return (
    <div className="mt-7 flex justify-end gap-3 border-t border-neutral-200 pt-5">
      <button
        className={secondaryButtonClassName}
        disabled={busy}
        onClick={onCancel}
        type="button"
      >
        Cancel
      </button>
      <button className={primaryButtonClassName} disabled={busy} type="submit">
        {busy ? "Saving…" : "Save"}
      </button>
    </div>
  );
}

export function FactoryFormDialog({
  companies,
  initial,
  onClose,
  onSave,
}: {
  readonly companies: readonly Company[];
  readonly initial?: Factory;
  readonly onClose: () => void;
  readonly onSave: (payload: FactoryInput) => Promise<void>;
}): ReactElement {
  const [companyId, setCompanyId] = useState(
    initial?.company_id ?? companies[0]?.id ?? "",
  );
  const [name, setName] = useState(initial?.name ?? "");
  const [location, setLocation] = useState(initial?.location ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setError(null);
    if (companyId === "" || name.trim() === "") {
      setError("Company and factory name are required.");
      return;
    }
    setBusy(true);
    try {
      await onSave({
        company_id: companyId,
        description: optionalText(description),
        location: optionalText(location),
        name: name.trim(),
      });
    } catch (caught) {
      setError(formError(caught));
      setBusy(false);
    }
  };

  return (
    <Dialog
      description="Factories belong to an existing company. Optional fields can be cleared."
      onClose={onClose}
      title={initial === undefined ? "Create factory" : "Edit factory"}
    >
      <form onSubmit={submit}>
        {error === null ? null : (
          <p
            className="mb-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            role="alert"
          >
            {error}
          </p>
        )}
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="factory-company">
              Company <span aria-hidden="true">*</span>
            </label>
            <select
              autoFocus
              className={inputClassName}
              disabled={busy}
              id="factory-company"
              onChange={(event) => setCompanyId(event.target.value)}
              required
              value={companyId}
            >
              <option value="">Select a company</option>
              {companies.map((company) => (
                <option key={company.id} value={company.id}>
                  {company.name}
                </option>
              ))}
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="factory-name">
              Factory name <span aria-hidden="true">*</span>
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="factory-name"
              maxLength={255}
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="factory-location">
              Location
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="factory-location"
              maxLength={255}
              onChange={(event) => setLocation(event.target.value)}
              value={location}
            />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="factory-description">
              Description
            </label>
            <textarea
              className={inputClassName}
              disabled={busy}
              id="factory-description"
              maxLength={1000}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              value={description}
            />
          </div>
        </div>
        <FormActions busy={busy} onCancel={onClose} />
      </form>
    </Dialog>
  );
}

export function MachineFormDialog({
  factory,
  initial,
  onClose,
  onSave,
}: {
  readonly factory: Factory;
  readonly initial?: Machine;
  readonly onClose: () => void;
  readonly onSave: (payload: MachineInput) => Promise<void>;
}): ReactElement {
  const [name, setName] = useState(initial?.name ?? "");
  const [serialNumber, setSerialNumber] = useState(initial?.serial_number ?? "");
  const [manufacturer, setManufacturer] = useState(initial?.manufacturer ?? "");
  const [model, setModel] = useState(initial?.model ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setError(null);
    if (name.trim() === "") {
      setError("Machine name is required.");
      return;
    }
    setBusy(true);
    try {
      await onSave({
        factory_id: factory.id,
        manufacturer: optionalText(manufacturer),
        model: optionalText(model),
        name: name.trim(),
        serial_number: optionalText(serialNumber),
      });
    } catch (caught) {
      setError(formError(caught));
      setBusy(false);
    }
  };

  return (
    <Dialog
      onClose={onClose}
      title={initial === undefined ? "Add machine" : "Edit machine"}
    >
      <form onSubmit={submit}>
        {error === null ? null : (
          <p
            className="mb-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            role="alert"
          >
            {error}
          </p>
        )}
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="machine-factory">
              Parent factory
            </label>
            <input
              className={inputClassName}
              disabled
              id="machine-factory"
              value={factory.name}
            />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="machine-name">
              Machine name <span aria-hidden="true">*</span>
            </label>
            <input
              autoFocus
              className={inputClassName}
              disabled={busy}
              id="machine-name"
              maxLength={255}
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </div>
          <div>
            <label className={labelClassName} htmlFor="machine-serial">
              Serial number
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="machine-serial"
              maxLength={255}
              onChange={(event) => setSerialNumber(event.target.value)}
              value={serialNumber}
            />
          </div>
          <div>
            <label className={labelClassName} htmlFor="machine-manufacturer">
              Manufacturer
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="machine-manufacturer"
              maxLength={255}
              onChange={(event) => setManufacturer(event.target.value)}
              value={manufacturer}
            />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="machine-model">
              Model
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="machine-model"
              maxLength={255}
              onChange={(event) => setModel(event.target.value)}
              value={model}
            />
          </div>
        </div>
        <FormActions busy={busy} onCancel={onClose} />
      </form>
    </Dialog>
  );
}

export function SensorFormDialog({
  initial,
  machine,
  onClose,
  onSave,
}: {
  readonly initial?: Sensor;
  readonly machine: Machine;
  readonly onClose: () => void;
  readonly onSave: (payload: SensorInput) => Promise<void>;
}): ReactElement {
  const [name, setName] = useState(initial?.name ?? "");
  const [sensorType, setSensorType] = useState(initial?.sensor_type ?? "");
  const [unit, setUnit] = useState(initial?.unit ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [samplingRate, setSamplingRate] = useState(
    String(initial?.sampling_rate ?? ""),
  );
  const [minValue, setMinValue] = useState(String(initial?.min_value ?? ""));
  const [maxValue, setMaxValue] = useState(String(initial?.max_value ?? ""));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setError(null);
    const rate = Number(samplingRate);
    const minimum = Number(minValue);
    const maximum = Number(maxValue);
    if (
      name.trim() === "" ||
      samplingRate === "" ||
      minValue === "" ||
      maxValue === ""
    ) {
      setError("Name, sampling rate, minimum, and maximum are required.");
      return;
    }
    if (!Number.isFinite(rate) || rate <= 0) {
      setError("Sampling rate must be greater than zero.");
      return;
    }
    if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || minimum >= maximum) {
      setError("Minimum value must be less than maximum value.");
      return;
    }
    setBusy(true);
    try {
      await onSave({
        description: optionalText(description),
        machine_id: machine.id,
        max_value: maximum,
        min_value: minimum,
        name: name.trim(),
        sampling_rate: rate,
        sensor_type: optionalText(sensorType),
        unit: optionalText(unit),
      });
    } catch (caught) {
      setError(formError(caught));
      setBusy(false);
    }
  };

  return (
    <Dialog
      onClose={onClose}
      title={initial === undefined ? "Add sensor" : "Edit sensor"}
    >
      <form onSubmit={submit}>
        {error === null ? null : (
          <p
            className="mb-5 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
            role="alert"
          >
            {error}
          </p>
        )}
        <div className="grid gap-5 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="sensor-machine">
              Parent machine
            </label>
            <input
              className={inputClassName}
              disabled
              id="sensor-machine"
              value={machine.name}
            />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="sensor-name">
              Sensor name <span aria-hidden="true">*</span>
            </label>
            <input
              autoFocus
              className={inputClassName}
              disabled={busy}
              id="sensor-name"
              maxLength={255}
              onChange={(event) => setName(event.target.value)}
              required
              value={name}
            />
          </div>
          <div>
            <label className={labelClassName} htmlFor="sensor-type">
              Sensor type
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="sensor-type"
              maxLength={255}
              onChange={(event) => setSensorType(event.target.value)}
              value={sensorType}
            />
          </div>
          <div>
            <label className={labelClassName} htmlFor="sensor-unit">
              Unit
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="sensor-unit"
              maxLength={64}
              onChange={(event) => setUnit(event.target.value)}
              value={unit}
            />
          </div>
          <div>
            <label className={labelClassName} htmlFor="sensor-rate">
              Sampling rate <span aria-hidden="true">*</span>
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="sensor-rate"
              min="0"
              onChange={(event) => setSamplingRate(event.target.value)}
              required
              step="any"
              type="number"
              value={samplingRate}
            />
          </div>
          <div>
            <label className={labelClassName} htmlFor="sensor-minimum">
              Minimum value <span aria-hidden="true">*</span>
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="sensor-minimum"
              onChange={(event) => setMinValue(event.target.value)}
              required
              step="any"
              type="number"
              value={minValue}
            />
          </div>
          <div>
            <label className={labelClassName} htmlFor="sensor-maximum">
              Maximum value <span aria-hidden="true">*</span>
            </label>
            <input
              className={inputClassName}
              disabled={busy}
              id="sensor-maximum"
              onChange={(event) => setMaxValue(event.target.value)}
              required
              step="any"
              type="number"
              value={maxValue}
            />
          </div>
          <div className="sm:col-span-2">
            <label className={labelClassName} htmlFor="sensor-description">
              Description
            </label>
            <textarea
              className={inputClassName}
              disabled={busy}
              id="sensor-description"
              maxLength={1000}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              value={description}
            />
          </div>
        </div>
        <FormActions busy={busy} onCancel={onClose} />
      </form>
    </Dialog>
  );
}
