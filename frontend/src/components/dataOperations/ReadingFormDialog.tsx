import { useState, type FormEvent, type ReactElement } from "react";

import { ApiError } from "../../api/client";
import { createSensorReading, type ReadingQuality } from "../../api/sensorData";
import type { Sensor } from "../../api/hierarchy";
import { Dialog } from "../hierarchy/Dialogs";
import {
  primaryButtonClassName,
  secondaryButtonClassName,
} from "../hierarchy/ResourceStates";

function localDateTimeNow(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

export function ReadingFormDialog({
  onClose,
  onCreated,
  sensor,
}: {
  readonly onClose: () => void;
  readonly onCreated: () => void;
  readonly sensor: Sensor;
}): ReactElement {
  const [timestamp, setTimestamp] = useState(localDateTimeNow());
  const [value, setValue] = useState("");
  const [quality, setQuality] = useState<ReadingQuality>("GOOD");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setError(null);
    const numericValue = Number(value);
    const parsedTimestamp = new Date(timestamp);
    if (value.trim() === "" || !Number.isFinite(numericValue)) {
      setError("Value must be a finite number.");
      return;
    }
    if (timestamp === "" || Number.isNaN(parsedTimestamp.getTime())) {
      setError("Enter a valid timestamp.");
      return;
    }
    setBusy(true);
    try {
      await createSensorReading({
        quality,
        sensor_id: sensor.id,
        source: "API",
        timestamp: parsedTimestamp.toISOString(),
        value: numericValue,
      });
      onCreated();
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "The reading could not be saved.",
      );
      setBusy(false);
    }
  };

  return (
    <Dialog
      description={`Create an API reading for ${sensor.name}.`}
      onClose={onClose}
      title="Add sensor reading"
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
            <label
              className="block text-sm font-medium text-neutral-800"
              htmlFor="reading-sensor"
            >
              Sensor
            </label>
            <input
              className="mt-2 block w-full rounded-md border border-neutral-300 bg-neutral-100 px-3 py-2.5 text-sm"
              disabled
              id="reading-sensor"
              value={sensor.name}
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-neutral-800"
              htmlFor="reading-timestamp"
            >
              Timestamp <span aria-hidden="true">*</span>
            </label>
            <input
              autoFocus
              className="mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm outline-none focus:border-purple-700 focus:ring-2 focus:ring-purple-700/20"
              disabled={busy}
              id="reading-timestamp"
              onChange={(event) => setTimestamp(event.target.value)}
              required
              type="datetime-local"
              value={timestamp}
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-neutral-800"
              htmlFor="reading-value"
            >
              Value{sensor.unit === null ? "" : ` (${sensor.unit})`}{" "}
              <span aria-hidden="true">*</span>
            </label>
            <input
              className="mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm outline-none focus:border-purple-700 focus:ring-2 focus:ring-purple-700/20"
              disabled={busy}
              id="reading-value"
              onChange={(event) => setValue(event.target.value)}
              required
              step="any"
              type="number"
              value={value}
            />
          </div>
          <div>
            <label
              className="block text-sm font-medium text-neutral-800"
              htmlFor="reading-quality"
            >
              Quality
            </label>
            <select
              className="mt-2 block w-full rounded-md border border-neutral-300 px-3 py-2.5 text-sm"
              disabled={busy}
              id="reading-quality"
              onChange={(event) => setQuality(event.target.value as ReadingQuality)}
              value={quality}
            >
              <option value="GOOD">Good</option>
              <option value="BAD">Bad</option>
              <option value="MISSING">Missing</option>
              <option value="OUTLIER">Outlier</option>
            </select>
          </div>
          <div>
            <label
              className="block text-sm font-medium text-neutral-800"
              htmlFor="reading-source"
            >
              Source
            </label>
            <input
              className="mt-2 block w-full rounded-md border border-neutral-300 bg-neutral-100 px-3 py-2.5 text-sm"
              disabled
              id="reading-source"
              value="API"
            />
          </div>
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
          <button className={primaryButtonClassName} disabled={busy} type="submit">
            {busy ? "Saving…" : "Add reading"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
